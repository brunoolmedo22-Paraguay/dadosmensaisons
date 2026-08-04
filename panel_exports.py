from __future__ import annotations

import html
import math
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

PALETTE = ["#7FB3D5", "#F4B4B4", "#B1DDBE", "#F8DD94", "#9B8FC4", "#6C8798"]


def _bounds(values: Sequence[float], include_zero: bool = False) -> tuple[float,float]:
    clean=[float(v) for v in values if pd.notna(v) and math.isfinite(float(v))]
    if not clean: return 0.0,1.0
    lo,hi=min(clean),max(clean)
    if include_zero: lo=min(lo,0); hi=max(hi,0)
    pad=max((hi-lo)*0.08, abs(hi)*0.02, 1e-9)
    return lo-pad, hi+pad


def line_svg(data: pd.DataFrame, x: str, series: Mapping[str,str], title: str, y_label: str="", width:int=1200, height:int=360) -> bytes:
    left,right,top,bottom=82,28,58,54
    pw,ph=width-left-right,height-top-bottom
    frame=data.copy()
    usable_series={label:column for label,column in series.items() if column in frame.columns}
    if frame.empty or x not in frame.columns or not usable_series:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="#fff"/><text x="40" y="42" font-family="Arial" font-size="20" font-weight="700" fill="#17383b">{html.escape(title)}</text><text x="40" y="90" font-family="Arial" font-size="14" fill="#526164">Sem dados para a configuração selecionada.</text></svg>').encode()
    series=usable_series
    frame[x]=pd.to_datetime(frame[x], errors="coerce") if not pd.api.types.is_numeric_dtype(frame[x]) else frame[x]
    values=[]
    for col in series.values(): values.extend(pd.to_numeric(frame[col],errors="coerce").dropna().tolist())
    lo,hi=_bounds(values)
    if pd.api.types.is_datetime64_any_dtype(frame[x]):
        xmin,xmax=frame[x].min(),frame[x].max(); span=max((xmax-xmin).total_seconds(),1)
        xpos=lambda v:left+(pd.Timestamp(v)-xmin).total_seconds()/span*pw
        ticks=pd.date_range(xmin,xmax,periods=min(8,max(2,len(frame))))
        ticklabels=[t.strftime("%Y") if span>365*86400 else t.strftime("%d/%m") for t in ticks]
    else:
        xv=pd.to_numeric(frame[x],errors="coerce"); xmin,xmax=float(xv.min()),float(xv.max()); span=max(xmax-xmin,1)
        xpos=lambda v:left+(float(v)-xmin)/span*pw
        ticks=np.linspace(xmin,xmax,min(12,max(2,len(frame)))); ticklabels=[f"{int(t)}" for t in ticks]
    ypos=lambda v:top+(hi-float(v))/(hi-lo)*ph
    nodes=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">','<rect width="100%" height="100%" fill="#fff"/>',f'<text x="{left}" y="30" font-family="Arial" font-size="20" font-weight="700" fill="#17383b">{html.escape(title)}</text>']
    for i in range(5):
        val=lo+i*(hi-lo)/4; y=ypos(val); nodes += [f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e1e9ea"/>',f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" font-family="Arial" font-size="11" fill="#526164">{val:.1f}</text>']
    for t,label in zip(ticks,ticklabels):
        xx=xpos(t); nodes += [f'<line x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" y2="{top+ph}" stroke="#f0f4f4"/>',f'<text x="{xx:.1f}" y="{height-23}" text-anchor="middle" font-family="Arial" font-size="11" fill="#526164">{html.escape(label)}</text>']
    legendx=left
    for idx,(label,col) in enumerate(series.items()):
        vals=pd.to_numeric(frame[col],errors="coerce"); valid=frame.loc[vals.notna(),[x]].copy(); valid["v"]=vals.dropna().values
        path=" ".join(f'{"M" if j==0 else "L"} {xpos(row[x]):.1f} {ypos(row["v"]):.1f}' for j,(_,row) in enumerate(valid.iterrows()))
        color=PALETTE[idx%len(PALETTE)]
        nodes.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        nodes += [f'<line x1="{legendx}" y1="46" x2="{legendx+22}" y2="46" stroke="{color}" stroke-width="4"/>',f'<text x="{legendx+28}" y="50" font-family="Arial" font-size="11" fill="#526164">{html.escape(label)}</text>']
        legendx += 45 + len(label)*7
    if y_label: nodes.append(f'<text x="18" y="{top+ph/2}" transform="rotate(-90 18 {top+ph/2})" text-anchor="middle" font-family="Arial" font-size="12" fill="#526164">{html.escape(y_label)}</text>')
    nodes.append('</svg>'); return ''.join(nodes).encode()


def bar_svg(labels: Sequence[str], values: Sequence[float], title: str, unit: str="", width:int=1200,height:int=380) -> bytes:
    left,right,top,bottom=190,36,55,35; pw,ph=width-left-right,height-top-bottom
    vals=[float(v) for v in values]; maxv=max([abs(v) for v in vals]+[1]); row=ph/max(len(vals),1)
    nodes=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">','<rect width="100%" height="100%" fill="#fff"/>',f'<text x="{left}" y="30" font-family="Arial" font-size="20" font-weight="700" fill="#17383b">{html.escape(title)}</text>']
    for i,(lab,val) in enumerate(zip(labels,vals)):
        y=top+i*row+row*.15; h=row*.7; w=abs(val)/maxv*pw; color=PALETTE[i%len(PALETTE)]
        nodes += [f'<text x="{left-10}" y="{y+h*.68:.1f}" text-anchor="end" font-family="Arial" font-size="11" fill="#526164">{html.escape(lab)}</text>',f'<rect x="{left}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{color}" rx="3"/>',f'<text x="{left+w+8:.1f}" y="{y+h*.68:.1f}" font-family="Arial" font-size="11" fill="#526164">{val:.2f} {html.escape(unit)}</text>']
    nodes.append('</svg>'); return ''.join(nodes).encode()


def heatmap_svg(matrix: pd.DataFrame, title: str, width:int=1200,height:int=480) -> bytes:
    left,right,top,bottom=75,35,58,50; pw,ph=width-left-right,height-top-bottom
    if matrix.empty: return line_svg(pd.DataFrame({"x":[0],"y":[0]}),"x",{"Sem dados":"y"},title)
    rows=list(matrix.index); cols=list(matrix.columns); vals=matrix.to_numpy(dtype=float); finite=vals[np.isfinite(vals)]; lo=float(finite.min()) if finite.size else 0; hi=float(finite.max()) if finite.size else 1; span=max(hi-lo,1e-9); cw=pw/max(len(cols),1); ch=ph/max(len(rows),1)
    nodes=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">','<rect width="100%" height="100%" fill="#fff"/>',f'<text x="{left}" y="30" font-family="Arial" font-size="20" font-weight="700" fill="#17383b">{html.escape(title)}</text>']
    for i,r in enumerate(rows):
        nodes.append(f'<text x="{left-8}" y="{top+(i+.65)*ch:.1f}" text-anchor="end" font-family="Arial" font-size="10" fill="#526164">{html.escape(str(r))}</text>')
        for j,c in enumerate(cols):
            v=vals[i,j]; ratio=0 if not np.isfinite(v) else (v-lo)/span; rr=int(238-120*ratio); gg=int(246-115*ratio); bb=int(246-75*ratio)
            nodes.append(f'<rect x="{left+j*cw:.1f}" y="{top+i*ch:.1f}" width="{cw+0.3:.1f}" height="{ch+0.3:.1f}" fill="rgb({rr},{gg},{bb})"/>')
    for j,c in enumerate(cols): nodes.append(f'<text x="{left+(j+.5)*cw:.1f}" y="{height-22}" text-anchor="middle" font-family="Arial" font-size="10" fill="#526164">{html.escape(str(c))}</text>')
    nodes.append('</svg>'); return ''.join(nodes).encode()


def combine_svgs(title: str, svgs: Sequence[bytes], width:int=1200) -> bytes:
    parts=[]; y=55; total=55
    for raw in svgs:
        txt=raw.decode(); hmatch=__import__('re').search(r'height="(\d+)"',txt); h=int(hmatch.group(1)) if hmatch else 360
        inner=txt[txt.find('>')+1:txt.rfind('</svg>')]
        parts.append(f'<g transform="translate(0,{y})">{inner}</g>'); y += h; total += h
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total}"><rect width="100%" height="100%" fill="#fff"/><text x="35" y="34" font-family="Arial" font-size="24" font-weight="700" fill="#17383b">{html.escape(title)}</text>{"".join(parts)}</svg>').encode()
