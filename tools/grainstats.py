import struct, sys, numpy as np
def read_main(fn):
    f=open(fn,"rb"); h=f.read(8); bo="<" if h[:2]==b"II" else ">"
    off=struct.unpack(bo+"I",h[4:])[0]
    def parse(off):
        f.seek(off); n=struct.unpack(bo+"H",f.read(2))[0]; d={}
        for i in range(n):
            e=f.read(12); tag,typ,cnt=struct.unpack(bo+"HHI",e[:8]); val=e[8:]
            sz={1:1,2:1,3:2,4:4,5:8,7:1}.get(typ,1)*cnt
            if sz>4:
                p=f.tell(); f.seek(struct.unpack(bo+"I",val)[0]); raw=f.read(sz); f.seek(p)
            else: raw=val[:sz]
            if typ==3: v=struct.unpack(bo+"%dH"%cnt,raw)
            elif typ==4: v=struct.unpack(bo+"%dI"%cnt,raw)
            else: v=raw
            d[tag]=v
        return d,struct.unpack(bo+"I",f.read(4))[0]
    ifds=[]
    while off:
        d,off=parse(off); ifds.append(d)
        if 330 in d:
            for so in d[330]: ifds.append(parse(so)[0])
    d=max(ifds,key=lambda d:d.get(256,(0,))[0])
    W,H=d[256][0],d[257][0]; spp=d[277][0]
    print("main IFD: %dx%d bps=%s spp=%d compression=%d photometric=%s linearization=%s"%(W,H,d[258],spp,d[259][0],d.get(262),50712 in d))
    for t,n in ((50714,"BlackLevel"),(50717,"WhiteLevel")):
        if t in d: print(" ",n,d[t][:4])
    buf=b"".join((f.seek(o),f.read(c))[1] for o,c in zip(d[273],d[279]))
    return np.frombuffer(buf,dtype=bo+"u2").reshape(H,W,spp)
for fn in sys.argv[1:]:
    print("==",fn)
    a=read_main(fn).astype(np.float64)
    g=a[...,1]
    print(" channel means R,G,B:",a.reshape(-1,a.shape[2]).mean(0).round(0), "max:",a.max())
    T=np.clip(g/65535.0,1e-4,1); D=-np.log10(T)
    print(" density pct 1/50/99:",np.percentile(D,[1,50,99]).round(2))
    P=24; Hh=(g.shape[0]//P)*P; Ww=(g.shape[1]//P)*P
    def patches(D):
        return D[:Hh,:Ww].reshape(Hh//P,P,Ww//P,P).transpose(0,2,1,3).reshape(-1,P*P)
    Dp=patches(D)
    yy,xx=np.mgrid[0:P,0:P]; A=np.stack([np.ones(P*P),yy.ravel(),xx.ravel()],1)
    coef=np.linalg.lstsq(A,Dp.T,rcond=None)[0]
    res=Dp-(A@coef).T
    m=Dp.mean(1); s=res.std(1)
    print(" density   n      sigmaD 10th   25th   median   (10th pct ~ flat patches = grain floor)")
    for lo in np.arange(0,3.0,0.2):
        k=(m>=lo)&(m<lo+0.2)
        if k.sum()>30: print("  %.1f-%.1f %6d    %.4f  %.4f  %.4f"%(lo,lo+0.2,k.sum(),*np.percentile(s[k],[10,25,50])))
    k=(m>0.5)&(m<1.5); idx=np.where(k)[0][np.argsort(s[k])[:500]]
    sel=res[idx].reshape(-1,P,P); sel=sel-sel.mean((1,2),keepdims=True)
    def ac(dx,dy):
        return (sel[:,dy:,dx:]*sel[:,:P-dy,:P-dx]).mean()/(sel**2).mean()
    print(" grain autocorr x lag1..5:",[round(ac(d,0),3) for d in range(1,6)])
    print(" grain autocorr y lag1..5:",[round(ac(0,d),3) for d in range(1,6)])
    def cc(x,y):
        x=x-x.mean(1,keepdims=True); y=y-y.mean(1,keepdims=True); return (x*y).sum()/np.sqrt((x*x).sum()*(y*y).sum())
    Dr=-np.log10(np.clip(a[...,0]/65535,1e-4,1)); Db=-np.log10(np.clip(a[...,2]/65535,1e-4,1))
    rp=patches(Dr)[idx]; bp=patches(Db)[idx]; gp=Dp[idx]
    rp=rp-(A@np.linalg.lstsq(A,rp.T,rcond=None)[0]).T; bp=bp-(A@np.linalg.lstsq(A,bp.T,rcond=None)[0]).T; gp=res[idx]
    print(" R-G / G-B grain correlation (flat midtone patches):",round(cc(rp,gp),3),round(cc(gp,bp),3))
    # skew of residual in flat patches: positive skew in density = sparse dark clumps on light ground
    r=sel.reshape(len(sel),-1); sk=((r-r.mean(1,keepdims=True))**3).mean(1)/r.std(1)**3
    print(" grain skewness (density domain), median over flat patches:",round(float(np.median(sk)),3))
