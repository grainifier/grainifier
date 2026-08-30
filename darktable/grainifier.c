/*
    grainifier — measured film grain for darktable.

    Copyright (C) 2026 Pontus Fyhr and grainifier contributors.

    This darktable module is free software: you can redistribute it and/or modify it under the
    terms of the GNU General Public License as published by the Free Software Foundation, either
    version 3 of the License, or (at your option) any later version.  (darktable modules link
    against darktable and are therefore GPL; the grainifier profiles are CC BY 4.0, the Python
    tool is MIT.)

    Model — see https://github.com/grainifier/grainifier:
      1. the pixel's luminance is a finished positive; place it on the negative through the scan
         curve  D = bp + (wp − bp) · L^(1/γ)
      2. add grain in density space: ΔD = σ_D(D) · skewed( n ),  n = white noise ⊛ measured kernel,
         evaluated on a lattice of the scanner's pitch expressed in film micrometres, so the grain
         has a physical size (the image's long side is `film width` mm of film)
      3. back to the positive with the same curve:  L' = L · ((D + ΔD − bp) / (D − bp))^γ
    Statistics (σ_D(D), skew(D), noise power spectrum) come from real scans, baked into
    grainifier_profiles.h by darktable/gen_profiles_header.py.
*/

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "bauhaus/bauhaus.h"
#include "common/math.h"
#include "control/control.h"
#include "develop/develop.h"
#include "develop/imageop.h"
#include "develop/imageop_gui.h"
#include "gui/gtk.h"
#include "iop/iop_api.h"
#include <gtk/gtk.h>

#include "grainifier_profiles.h"

DT_MODULE_INTROSPECTION(1, dt_iop_grainifier_params_t)

typedef enum dt_iop_grainifier_profile_t
{
  DT_GRAINIFIER_HP5_1600 = 0,      // $DESCRIPTION: "Ilford HP5+ @ 1600"
  DT_GRAINIFIER_BWXX = 1,          // $DESCRIPTION: "Kodak Double-X 5222"
  DT_GRAINIFIER_HP5_1600_SOFT = 2, // $DESCRIPTION: "Ilford HP5+ @ 1600 (softer scan)"
  DT_GRAINIFIER_BWXX_SOFT = 3,     // $DESCRIPTION: "Kodak Double-X (softer scan)"
  DT_GRAINIFIER_BWXX_PUSH2 = 4,    // $DESCRIPTION: "Kodak Double-X push 2"
} dt_iop_grainifier_profile_t;

typedef struct dt_iop_grainifier_params_t
{
  dt_iop_grainifier_profile_t profile; // $DEFAULT: DT_GRAINIFIER_HP5_1600 $DESCRIPTION: "film"
  float film_width;   // $MIN: 8.0 $MAX: 120.0 $DEFAULT: 36.0 $DESCRIPTION: "film width"
  float grain_scale;  // $MIN: 0.0 $MAX: 3.0 $DEFAULT: 1.0 $DESCRIPTION: "grain amount"
  float black_point;  // $MIN: 0.0 $MAX: 1.0 $DEFAULT: 0.03 $DESCRIPTION: "black point"
  float white_point;  // $MIN: 1.5 $MAX: 3.5 $DEFAULT: 2.6 $DESCRIPTION: "white point"
  float gamma;        // $MIN: 0.5 $MAX: 3.0 $DEFAULT: 1.45 $DESCRIPTION: "positive gamma"
  int seed;           // $MIN: 0 $MAX: 9999 $DEFAULT: 0 $DESCRIPTION: "seed"
} dt_iop_grainifier_params_t;

typedef struct dt_iop_grainifier_gui_data_t
{
  GtkWidget *profile, *film_width, *grain_scale, *black_point, *white_point, *gamma, *seed;
} dt_iop_grainifier_gui_data_t;

typedef struct dt_iop_grainifier_data_t
{
  const grainifier_profile_t *profile;
  float film_width_um;
  float grain_scale;
  float black_point, white_point, gamma;
  uint32_t seed;
  float skew_a[GRAINIFIER_GRID_N]; // skew(D) converted to the cubic-transform coefficient
  // normalised lag-1 autocorrelations of the grain field per kernel (index 0 = fine kernel,
  // 1.. = decimated), used to keep unit variance when interpolating between lattice nodes
  float rho_x[GRAINIFIER_N_DEC + 1], rho_y[GRAINIFIER_N_DEC + 1], rho_xy[GRAINIFIER_N_DEC + 1];
} dt_iop_grainifier_data_t;

// autocorrelation of (white noise ⊛ k) at lag (dx, dy), normalised by lag 0
static void _kernel_rho(const float *k, const int K, float *rx, float *ry, float *rxy)
{
  double r00 = 0, r10 = 0, r01 = 0, r11 = 0;
  for(int y = 0; y < K; y++)
    for(int x = 0; x < K; x++)
    {
      const double v = k[y * K + x];
      r00 += v * v;
      if(x + 1 < K) r10 += v * k[y * K + x + 1];
      if(y + 1 < K) r01 += v * k[(y + 1) * K + x];
      if(x + 1 < K && y + 1 < K) r11 += v * k[(y + 1) * K + x + 1];
    }
  *rx = r10 / r00; *ry = r01 / r00; *rxy = r11 / r00;
}


const char *name()
{
  return _("grainifier");
}

const char *aliases()
{
  return _("film grain|measured grain");
}

const char **description(dt_iop_module_t *self)
{
  return dt_iop_set_description(self,
                                _("measured film grain, rendered in negative-density space"),
                                _("creative"),
                                _("linear, RGB, display-referred"),
                                _("non-linear, RGB"),
                                _("linear, RGB, display-referred"));
}

int flags()
{
  return IOP_FLAGS_INCLUDE_IN_STYLES | IOP_FLAGS_SUPPORTS_BLENDING;
}

int default_group()
{
  return IOP_GROUP_EFFECT | IOP_GROUP_EFFECTS;
}

dt_iop_colorspace_type_t default_colorspace(dt_iop_module_t *self,
                                            dt_dev_pixelpipe_t *pipe,
                                            dt_dev_pixelpipe_iop_t *piece)
{
  return IOP_CS_RGB;
}

/* ------------------------------------------------------------------ noise lattice */

// 2-D integer hash → uniform in (0,1). lowbias32-style mixing on the cell index and seed.
static inline uint32_t _mix(uint32_t x)
{
  x ^= x >> 16;
  x *= 0x7feb352dU;
  x ^= x >> 15;
  x *= 0x846ca68bU;
  x ^= x >> 16;
  return x;
}

static inline float _lattice_gauss(const int32_t cx, const int32_t cy, const uint32_t seed)
{
  const uint32_t h = _mix((uint32_t)cx * 0x9E3779B1U ^ _mix((uint32_t)cy * 0x85EBCA77U ^ seed));
  const uint32_t h2 = _mix(h ^ 0x5bd1e995U);
  // Box–Muller with two uniforms; one Gaussian per cell
  const float u1 = ((h >> 8) + 1.0f) * (1.0f / 16777217.0f);
  const float u2 = (h2 >> 8) * (1.0f / 16777216.0f);
  return sqrtf(-2.0f * logf(u1)) * cosf(2.0f * (float)M_PI * u2);
}

static inline float _interp_grid(const float *tab, float d)
{
  d = CLAMP(d, 0.0f, (GRAINIFIER_GRID_N - 1) * GRAINIFIER_GRID_STEP);
  const float x = d / GRAINIFIER_GRID_STEP;
  const int i = MIN((int)x, GRAINIFIER_GRID_N - 2);
  const float t = x - i;
  return tab[i] * (1.0f - t) + tab[i + 1] * t;
}

// skewness of (n + a(n²−1))/sqrt(1+2a²) for n ~ N(0,1) is (6a + 8a³)/(1+2a²)^1.5; invert by bisection
static float _skew_to_a(const float s)
{
  float lo = -0.6f, hi = 0.6f;
  for(int it = 0; it < 40; it++)
  {
    const float a = 0.5f * (lo + hi);
    const float sk = (6.0f * a + 8.0f * a * a * a) / powf(1.0f + 2.0f * a * a, 1.5f);
    if(sk < s) lo = a; else hi = a;
  }
  return 0.5f * (lo + hi);
}

/* ------------------------------------------------------------------ process */

void process(dt_iop_module_t *self,
             dt_dev_pixelpipe_iop_t *piece,
             const void *const ivoid,
             void *const ovoid,
             const dt_iop_roi_t *const roi_in,
             const dt_iop_roi_t *const roi_out)
{
  if(!dt_iop_have_required_input_format(4, self, piece->colors, ivoid, ovoid, roi_in, roi_out))
    return;

  const dt_iop_grainifier_data_t *const d = piece->data;
  const grainifier_profile_t *const prof = d->profile;

  // full-image geometry: buf_in is the pipe's input size at scale 1 for this pipe; roi_out->scale
  // maps it to the current output resolution. The image's long side spans film_width µm of film.
  const float full_w = piece->buf_in.width, full_h = piece->buf_in.height;
  const float long_side = MAX(full_w, full_h);
  const float pitch_full = d->film_width_um / long_side;       // µm per full-resolution pixel
  const float pitch_out = pitch_full / roi_out->scale;          // µm per output pixel in this ROI

  // lattice: the scanner pitch, or coarser (decimated) when the output pixel is coarser. Pick the
  // decimation nearest (in log) to the pitch ratio and correct its variance to the value the exact
  // box-averaged field would have at this ratio (log-log interpolation of the tabulated variances).
  const float ratio = pitch_out / prof->pitch_um;
  int dec = 0;
  float var_scale = 1.0f;
  if(ratio > 1.0f)
  {
    const float lr = logf(ratio);
    float best = 1e9f;
    for(int k = 0; k < GRAINIFIER_N_DEC; k++)
    {
      const float dist = fabsf(logf((float)grainifier_decimations[k]) - lr);
      if(dist < best) { best = dist; dec = k; }
    }
    // interpolate the true variance between the bracketing table entries
    int lo = 0;
    while(lo + 1 < GRAINIFIER_N_DEC && grainifier_decimations[lo + 1] <= ratio) lo++;
    float var_true;
    if(lo + 1 < GRAINIFIER_N_DEC)
    {
      const float l0 = logf((float)grainifier_decimations[lo]), l1 = logf((float)grainifier_decimations[lo + 1]);
      const float t = (lr - l0) / (l1 - l0);
      var_true = expf(logf(prof->dec_var[lo]) * (1.0f - t) + logf(prof->dec_var[lo + 1]) * t);
    }
    else
      var_true = prof->dec_var[lo] * powf((float)grainifier_decimations[lo] / ratio, 2.0f); // beyond the table: ~1/area
    var_scale = sqrtf(var_true / prof->dec_var[dec]);
  }
  const int m = grainifier_decimations[dec];
  const float lattice_um = prof->pitch_um * m;
  const int K = (m == 1) ? GRAINIFIER_KERNEL : GRAINIFIER_DEC_KERNEL;
  const int Kh = K / 2;
  const float *const kernel = (m == 1) ? prof->kernel : prof->dec_kernel[dec];
  const int ri = (m == 1) ? 0 : dec + 1;
  const float rho_x = d->rho_x[ri], rho_y = d->rho_y[ri], rho_xy = d->rho_xy[ri];
  // fine lattice with the full 15×15 kernel has unit variance; decimated kernels carry theirs
  const float amount = d->grain_scale * var_scale;
  const float bp = d->black_point, wp = d->white_point, gam = d->gamma;
  const float inv_gam = 1.0f / gam;
  const uint32_t seed = d->seed;
  const int ch = 4;

  DT_OMP_FOR()
  for(int j = 0; j < roi_out->height; j++)
  {
    const float *in = (const float *)ivoid + (size_t)ch * roi_out->width * j;
    float *out = (float *)ovoid + (size_t)ch * roi_out->width * j;
    const float fy_um = ((roi_out->y + j) + 0.5f) * pitch_out;   // film position of the pixel centre
    const float ly = fy_um / lattice_um;
    const int32_t cy0 = (int32_t)floorf(ly);
    const float ty = ly - cy0;

    for(int i = 0; i < roi_out->width; i++, in += ch, out += ch)
    {
      const float fx_um = ((roi_out->x + i) + 0.5f) * pitch_out;
      const float lx = fx_um / lattice_um;
      const int32_t cx0 = (int32_t)floorf(lx);
      const float tx = lx - cx0;

      // luminance of the finished positive (linear working RGB → Rec.709 luma is close enough for B&W)
      const float L = CLAMP(0.2126f * in[0] + 0.7152f * in[1] + 0.0722f * in[2], 0.0f, 1.0f);
      const float D = bp + (wp - bp) * powf(L, inv_gam);

      // grain field: white lattice noise ⊛ kernel, bilinearly interpolated between lattice nodes so
      // that pixels finer than the lattice (zoomed-in views, > 4000 dpi images) stay smooth
      float n = 0.0f;
      const float wa = (1.0f - tx) * (1.0f - ty), wb = tx * (1.0f - ty), wc = (1.0f - tx) * ty, wd = tx * ty;
      const float wts[4] = { wa, wb, wc, wd };
      for(int q = 0; q < 2; q++)
        for(int p = 0; p < 2; p++)
        {
          const float w = wts[q * 2 + p];
          if(w < 1e-4f) continue;
          const int32_t cx = cx0 + p, cy = cy0 + q;
          float acc = 0.0f;
          for(int ky = -Kh; ky <= Kh; ky++)
          {
            const float *krow = kernel + (size_t)(ky + Kh) * K;
            for(int kx = -Kh; kx <= Kh; kx++)
              acc += krow[kx + Kh] * _lattice_gauss(cx - kx, cy - ky, seed);
          }
          n += w * acc;
        }
      // interpolating between correlated nodes lowers the variance; restore it exactly
      const float var = wa * wa + wb * wb + wc * wc + wd * wd
                        + 2.0f * ((wa * wb + wc * wd) * rho_x + (wa * wc + wb * wd) * rho_y + (wa * wd + wb * wc) * rho_xy);
      n /= sqrtf(MAX(var, 1e-6f));

      // skew and amplitude at this density
      const float a = _interp_grid(d->skew_a, D);
      const float ns = (n + a * (n * n - 1.0f)) / sqrtf(1.0f + 2.0f * a * a);
      const float dD = ns * _interp_grid(prof->sigma, D) * amount;

      // back to the positive through the same curve; bounded near the black point
      const float base = MAX(D - bp, 0.02f);
      const float ratio_l = powf(MAX(D + dD - bp, 0.0f) / base, gam);

      out[0] = in[0] * ratio_l;
      out[1] = in[1] * ratio_l;
      out[2] = in[2] * ratio_l;
      out[3] = in[3];
    }
  }
}

void commit_params(dt_iop_module_t *self,
                   dt_iop_params_t *p1,
                   dt_dev_pixelpipe_t *pipe,
                   dt_dev_pixelpipe_iop_t *piece)
{
  const dt_iop_grainifier_params_t *p = (dt_iop_grainifier_params_t *)p1;
  dt_iop_grainifier_data_t *d = piece->data;

  const int idx = CLAMP((int)p->profile, 0, GRAINIFIER_N_PROFILES - 1);
  d->profile = grainifier_profiles[idx];
  d->film_width_um = p->film_width * 1000.0f;
  d->grain_scale = p->grain_scale;
  d->black_point = p->black_point;
  d->white_point = MAX(p->white_point, p->black_point + 0.5f);
  d->gamma = p->gamma;
  d->seed = (uint32_t)p->seed * 2654435761U + 12345U;
  for(int i = 0; i < GRAINIFIER_GRID_N; i++) d->skew_a[i] = _skew_to_a(d->profile->skew[i]);
  _kernel_rho(d->profile->kernel, GRAINIFIER_KERNEL, &d->rho_x[0], &d->rho_y[0], &d->rho_xy[0]);
  for(int k = 0; k < GRAINIFIER_N_DEC; k++)
    _kernel_rho(d->profile->dec_kernel[k], GRAINIFIER_DEC_KERNEL, &d->rho_x[k + 1], &d->rho_y[k + 1], &d->rho_xy[k + 1]);
}

void init_pipe(dt_iop_module_t *self, dt_dev_pixelpipe_t *pipe, dt_dev_pixelpipe_iop_t *piece)
{
  piece->data = calloc(1, sizeof(dt_iop_grainifier_data_t));
}

void cleanup_pipe(dt_iop_module_t *self, dt_dev_pixelpipe_t *pipe, dt_dev_pixelpipe_iop_t *piece)
{
  free(piece->data);
  piece->data = NULL;
}

void gui_init(dt_iop_module_t *self)
{
  dt_iop_grainifier_gui_data_t *g = IOP_GUI_ALLOC(grainifier);

  g->profile = dt_bauhaus_combobox_from_params(self, "profile");
  gtk_widget_set_tooltip_text(g->profile, _("film stock / development / scan the grain statistics were measured from"));

  g->film_width = dt_bauhaus_slider_from_params(self, "film_width");
  dt_bauhaus_slider_set_format(g->film_width, " mm");
  dt_bauhaus_slider_set_digits(g->film_width, 0);
  gtk_widget_set_tooltip_text(g->film_width, _("width of film the image's long side corresponds to: 36 = 35 mm full frame, 24 = half frame, 56 = 6×6. sets the physical grain size"));

  g->grain_scale = dt_bauhaus_slider_from_params(self, "grain_scale");
  dt_bauhaus_slider_set_digits(g->grain_scale, 2);
  gtk_widget_set_tooltip_text(g->grain_scale, _("multiplier on the measured grain amplitude (1 = as measured)"));

  g->black_point = dt_bauhaus_slider_from_params(self, "black_point");
  dt_bauhaus_slider_set_digits(g->black_point, 2);
  gtk_widget_set_tooltip_text(g->black_point, _("negative density that maps to black in the positive (≈ base + fog)"));

  g->white_point = dt_bauhaus_slider_from_params(self, "white_point");
  dt_bauhaus_slider_set_digits(g->white_point, 2);
  gtk_widget_set_tooltip_text(g->white_point, _("negative density that maps to white in the positive"));

  g->gamma = dt_bauhaus_slider_from_params(self, "gamma");
  dt_bauhaus_slider_set_digits(g->gamma, 2);
  gtk_widget_set_tooltip_text(g->gamma, _("gamma of the scan-style positive: 1.45 ≈ VueScan inversion, 2.2 ≈ Lightroom / Negative Lab Pro (grainier)"));

  g->seed = dt_bauhaus_slider_from_params(self, "seed");
  dt_bauhaus_slider_set_digits(g->seed, 0);
  gtk_widget_set_tooltip_text(g->seed, _("changes the random grain pattern"));
}

// clang-format off
// vim: shiftwidth=2 expandtab tabstop=2 cindent
// kate: tab-indents: off; indent-width 2; replace-tabs on; indent-mode cstyle; remove-trailing-spaces modified;
// clang-format on
