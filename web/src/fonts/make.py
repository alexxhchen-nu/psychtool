# Builds the embedded fonts for the GitBook-derived theme.
# Body/headings: Inter (SIL OFL 1.1) static instances from the variable font, Latin subset, renamed "Proto Sans".
# Mono: IBM Plex Mono (SIL OFL 1.1, RFN "Plex"), reused from ../fonts (already renamed "Proto Mono").
# GitBook's heading face "General Sans" (Indian Type Foundry, ITF Free Font License, not OFL) is NOT embedded.
import io,base64,os
from fontTools.ttLib import TTFont
from fontTools import subset
from fontTools.varLib import instancer
P='/usr/share/fonts/truetype/sand-box/google/Inter/'
RANGES='U+0000-024F,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0300-0308,U+0329,U+2000-206F,U+20AC,U+2116,U+2122,U+2190-2193,U+2212,U+2215,U+2264-2265,U+00B0,U+00B1,U+00D7,U+2713,U+FEFF,U+FFFD'
def cps(r):
    out=[]
    for part in r.split(','):
        a=part[2:].split('-');lo=int(a[0],16);hi=int(a[-1],16);out+=range(lo,hi+1)
    return out
faces=[('Inter-VariableFont_opsz,wght.ttf',400,'normal','Regular'),('Inter-VariableFont_opsz,wght.ttf',600,'normal','SemiBold'),
       ('Inter-VariableFont_opsz,wght.ttf',700,'normal','Bold'),('Inter-Italic-VariableFont_opsz,wght.ttf',400,'italic','Italic')]
FAM='Proto Sans'
for f,w,s,style in faces:
    vf=TTFont(P+f)
    lic=(vf['name'].getDebugName(13) or '')[:120];cr=vf['name'].getDebugName(0)
    t=instancer.instantiateVariableFont(vf,{'wght':w,'opsz':14})
    opt=subset.Options();opt.flavor='woff2';opt.name_IDs=['*'];opt.name_languages=['*'];opt.layout_features=['kern','liga','calt','ccmp','locl','mark','mkmk','tnum','case'];opt.notdef_outline=True;opt.hinting=False
    sub=subset.Subsetter(opt);sub.populate(unicodes=cps(RANGES));sub.subset(t)
    nm=t['name']
    for rec in list(nm.names):
        if rec.nameID in (1,16): rec.string=FAM
        elif rec.nameID==4: rec.string=FAM+' '+style
        elif rec.nameID==6: rec.string='ProtoSans-'+style
        elif rec.nameID==3: rec.string='ProtoSans-'+style+';subset-for-psychtool-prototype'
        elif rec.nameID in (2,17): rec.string=style
        elif rec.nameID==10: rec.string='Static Latin subset of Inter (The Inter Project Authors), renamed for the psychtool prototype under SIL OFL 1.1.'
    nm.names=[r for r in nm.names if r.nameID<256 or r.nameID in ()]  # drop variable-axis instance names
    b=io.BytesIO();t.flavor='woff2';t.save(b);data=b.getvalue()
    out=f'sans-{w}-{s}.woff2';open(out,'wb').write(data)
    print(out,len(data),'copyright:',cr,'| license:',lic)
