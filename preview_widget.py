"""Cached depth-aware top/side preview with pan, zoom and draggable tabs."""
from dataclasses import dataclass
import math
import tkinter as tk
from tkinter import ttk
from shapely.geometry import LineString, Point
from preview import COLORS
from tabs import tab_centres
from work_control import checkpoint


@dataclass
class PreviewData:
    job: object
    segments: list
    levels: list
    bounds: tuple


def prepare_preview(job, cancel=None):
    x = y = None
    z = job.settings.safe_z
    seen, segments = set(), []
    for i, move in enumerate(job.moves):
        if i % 1024 == 0:
            checkpoint(cancel)
        nx, ny, nz = move.x if move.x is not None else x, move.y if move.y is not None else y, move.z if move.z is not None else z
        if x is not None and nx is not None:
            seg = (x,y,z,nx,ny,nz,move.code,move.op,move.tab,move.level)
            if seg not in seen:
                seen.add(seg)
                segments.append(seg)
        x,y,z = nx,ny,nz
    points = [(x,y) for plan in job.plans for path in plan.paths for x,y in path]
    bounds = (min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points))
    return PreviewData(job,segments,sorted({m.level for m in job.moves if m.level is not None},reverse=True),bounds)


class ToolpathPreview(ttk.Frame):
    def __init__(self, parent, on_tab_move):
        super().__init__(parent)
        self.on_tab_move = on_tab_move
        self.data = None
        self.drawing = None
        self.zoom = 1.0
        self.pan = [0.0,0.0]
        self.drag = None
        self.redraw_id = None
        self.closed = False
        self.operation = tk.StringVar(value="All operations")
        self.view = tk.StringVar(value="Top XY")
        self.pass_index = tk.DoubleVar(value=0)
        self.show_width = tk.BooleanVar(value=False)
        self.caption = tk.StringVar(value="Load a drawing to preview it.")
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.op_box = ttk.Combobox(bar,textvariable=self.operation,values=("All operations",),state="readonly",width=22)
        self.op_box.pack(side="left",padx=3)
        ttk.Combobox(bar,textvariable=self.view,values=("Top XY","Side XZ"),state="readonly",width=10).pack(side="left",padx=3)
        ttk.Button(bar,text="Fit",command=self.fit).pack(side="left",padx=3)
        ttk.Checkbutton(bar,text="Cutter width",variable=self.show_width).pack(side="left")
        self.canvas = tk.Canvas(self,background="#fafafa",highlightthickness=0)
        self.canvas.pack(fill="both",expand=True)
        self.slider = ttk.Scale(self,from_=0,to=1,variable=self.pass_index,command=lambda _:self.schedule())
        self.slider.pack(fill="x",padx=8)
        ttk.Label(self,textvariable=self.caption,wraplength=760).pack(anchor="w",padx=8,pady=4)
        ttk.Label(self,text="Wheel: zoom · Drag background: pan · Drag orange tab handles: reposition\nSolid: cuts · Dashed: rapids · Red: uncleared pocket boundaries · Side view: plunges/retracts",wraplength=760).pack(anchor="w",padx=8,pady=4)
        for variable in (self.operation,self.view,self.show_width):
            variable.trace_add("write",lambda *_:self.schedule())
        self.view.trace_add("write",lambda *_:self.fit())
        self.canvas.bind("<Configure>",lambda _:self.schedule())
        self.canvas.bind("<MouseWheel>",self.wheel)
        self.canvas.bind("<Button-4>",lambda e:self.wheel(e,1))
        self.canvas.bind("<Button-5>",lambda e:self.wheel(e,-1))
        self.canvas.bind("<ButtonPress-1>",self.press)
        self.canvas.bind("<B1-Motion>",self.motion)
        self.canvas.bind("<ButtonRelease-1>",self.release)

    def destroy(self):
        self.closed=True
        if self.redraw_id:
            self.after_cancel(self.redraw_id)
        super().destroy()

    def set_drawing(self,drawing):
        self.drawing=drawing
        self.data=None
        self.fit()

    def set_data(self,data):
        self.data=data
        self.op_box.configure(values=("All operations", *[f"{i+1}: {p.operation.name}" for i,p in enumerate(data.job.plans)]))
        if self.operation.get() not in self.op_box["values"]:
            self.operation.set("All operations")
        self.slider.configure(to=len(data.levels))
        self.pass_index.set(0)
        self.schedule()

    def fit(self):
        self.zoom=1.0
        self.pan=[0.0,0.0]
        self.schedule()

    def schedule(self):
        if self.closed:return
        if self.redraw_id:
            self.after_cancel(self.redraw_id)
        self.redraw_id=self.after(45,self.draw)

    def transform(self):
        bounds=self.data.bounds if self.data else self.drawing.bounds
        x0,y0,x1,y1=bounds
        if self.view.get()=="Side XZ":
            y0=-max((p.operation.depth for p in self.data.job.plans),default=1) if self.data else -1
            y1=self.data.job.settings.safe_z if self.data else 5
        width,height=max(100,self.canvas.winfo_width()),max(100,self.canvas.winfo_height())
        scale=min((width-70)/max(x1-x0,1),(height-70)/max(y1-y0,1))*self.zoom
        return scale,35-x0*scale+self.pan[0],height-35+y0*scale+self.pan[1]

    def xy(self,x,y):
        scale,ox,oy=self.transform()
        return ox+x*scale,oy-y*scale

    def world(self,x,y):
        scale,ox,oy=self.transform()
        return (x-ox)/scale,(oy-y)/scale

    def wheel(self,event,direction=None):
        if not self.drawing:
            return
        wx,wy=self.world(event.x,event.y)
        self.zoom=max(.15,min(30,self.zoom*(1.2 if (direction or event.delta)>0 else 1/1.2)))
        nx,ny=self.xy(wx,wy)
        self.pan[0]+=event.x-nx
        self.pan[1]+=event.y-ny
        self.schedule()

    def selected_op(self):
        return None if self.operation.get()=="All operations" else int(self.operation.get().split(":")[0])-1

    def filtered_segments(self):
        if not self.data:
            return []
        index=min(len(self.data.levels),int(round(self.pass_index.get())))
        level=self.data.levels[index-1] if index else None
        op=self.selected_op()
        return [s for s in self.data.segments if (op is None or s[7]==op) and (level is None or s[9]==level)]

    def draw(self):
        if self.redraw_id:
            self.after_cancel(self.redraw_id)
        self.redraw_id=None
        self.canvas.delete("all")
        if not self.drawing:
            self.canvas.create_text(25,35,anchor="nw",text="Load a drawing to see its geometry.")
            return
        top=self.view.get()=="Top XY"
        if top:
            for path in self.drawing.paths:
                self.canvas.create_line(*[v for p in path for v in self.xy(*p)],fill="#bec5cd")
        segments=self.filtered_segments()
        scale=self.transform()[0]
        # Cache generation removes identical paths; render in this fitted view.
        for x,y,z,u,v,w,code,op,tab,level in segments:
            a,b=self.xy(x,y if top else z)
            c,d=self.xy(u,v if top else w)
            vertical=abs(x-u)+abs(y-v)<1e-9
            if self.show_width.get() and top and code=="G1" and not vertical:
                width=self.data.job.plans[op].operation.tool_diameter*scale
                self.canvas.create_line(a,b,c,d,width=max(1,width),fill="#dce7f0",capstyle="round")
            color="#d9830a" if tab else "#a4b1c0" if code=="G0" else COLORS[op%len(COLORS)]
            if vertical and top:
                if code=="G1":
                    self.canvas.create_oval(a-2,b-2,a+2,b+2,outline="#b92432")
            else:
                self.canvas.create_line(a,b,c,d,fill=color,width=2 if tab else 1.2,dash=(4,5) if code=="G0" else ())
        if self.data and top:
            selected=self.selected_op()
            for i,plan in enumerate(self.data.job.plans):
                if selected is not None and selected!=i:
                    continue
                for path in plan.remaining_paths:
                    self.canvas.create_line(*[v for p in path for v in self.xy(*p)],fill="#c32938",width=2)
                for j,path in enumerate(plan.paths):
                    line=LineString(path)
                    for k,fraction in enumerate(tab_centres(path,plan.operation)):
                        point=line.interpolate(fraction,normalized=True)
                        x,y=self.xy(point.x,point.y)
                        self.canvas.create_oval(x-6,y-6,x+6,y+6,fill="#f4a42b",outline="#8b5100",width=2,tags=(f"tab:{i}:{j}:{k}",))
        index=min(len(self.data.levels),int(round(self.pass_index.get()))) if self.data else 0
        label=f"Pass Z = {self.data.levels[index-1]:g} mm" if index else "All depth passes"
        self.caption.set(label+" · Cutter-centre motion; no stock or fixture collision simulation.")

    def press(self,event):
        if not self.drawing:
            return
        tags=[]
        for item in self.canvas.find_overlapping(event.x-4,event.y-4,event.x+4,event.y+4):
            tags.extend(self.canvas.gettags(item))
        tab=next((t for t in tags if t.startswith("tab:")),None)
        self.drag=(tab,event.x,event.y)

    def motion(self,event):
        if not self.drag:
            return
        tag,x,y=self.drag
        if tag:
            self.canvas.move(tag,event.x-x,event.y-y)
        else:
            self.pan[0]+=event.x-x
            self.pan[1]+=event.y-y
            self.schedule()
        self.drag=(tag,event.x,event.y)

    def release(self,event):
        if self.drag and self.drag[0] and self.data:
            _,op,path,tab=self.drag[0].split(":")
            line=LineString(self.data.job.plans[int(op)].paths[int(path)])
            fraction=line.project(Point(*self.world(event.x,event.y)),normalized=True)%1
            self.on_tab_move(int(op),int(path),int(tab),fraction)
        self.drag=None
        self.schedule()
