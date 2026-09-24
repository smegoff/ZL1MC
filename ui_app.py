"""Desktop workflow: explicit edits, background tasks and versioned jobs."""
from __future__ import annotations
from dataclasses import asdict
import copy
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cam import VERSION, MODES, CamError, Operation, Settings, build_job, load_dxf
from persistence import (export_job, export_paths, fingerprint, read_config,
                         recover_export, save_config, transaction_dir, validate_import)
from preview_widget import ToolpathPreview, prepare_preview
from tabs import contour_key, tab_centres
from tk_support import prepare_tk
from work_control import Cancelled

prepare_tk()


class ScrollFrame(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,highlightthickness=0)
        scroll=ttk.Scrollbar(self,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right",fill="y")
        self.canvas.pack(side="left",fill="both",expand=True)
        self.body=ttk.Frame(self.canvas,padding=8)
        self.window=self.canvas.create_window(0,0,window=self.body,anchor="nw")
        self.body.bind("<Configure>",lambda _:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(self.window,width=e.width))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"DXF → G-code · 2.5D {VERSION} — experimental")
        self.geometry("1320x900")
        self.minsize(1000,700)
        self.drawing=self.job=None
        self.operations=[]
        self.loaded_signature=None
        self.loaded_hash=""
        self.busy=False
        self.results=queue.Queue()
        self.cancel_event=threading.Event()
        self.revision=0
        self.active_index=None
        self.editor_loading=False
        self.editor_baseline={}
        self.custom_tabs={}
        self.undo_stack=[]
        self.redo_stack=[]
        self.job_dirty=False
        self.dxf=tk.StringVar()
        self.source_units=tk.StringVar(value="Auto")
        self.scale=tk.StringVar(value="1")
        self.tolerance=tk.StringVar(value="0.02")
        self.origin=tk.StringVar(value="Drawing origin")
        initial=asdict(Settings(check_setup=True))
        self.setup_vars={k:(tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=str(v))) for k,v in initial.items()}
        self.safe_z=self.setup_vars["safe_z"]
        self.spindle=self.setup_vars["spindle"]
        self.spindle_on=self.setup_vars["spindle_on"]
        self.fields={k:tk.StringVar(value=str(v)) for k,v in asdict(Operation()).items() if k!="tab_positions"}
        self.pending=tk.StringVar(value="No pending operation edits")
        self.status=tk.StringVar(value="Load a drawing. Verify machine setup before exporting.")
        self.summary=tk.StringVar(value="No built job")
        self._build()
        for var in (self.dxf,self.source_units,self.scale,self.tolerance,self.origin,*self.setup_vars.values()):
            var.trace_add("write",self.invalidate)
        for var in self.fields.values():
            var.trace_add("write",self.editor_changed)
        self.set_editor(None)
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.bind("<Control-s>",lambda _:self.save_config())
        self.bind("<Control-o>",lambda _:self.open_config())
        self.bind("<Control-z>",lambda _:self.undo())
        self.bind("<Control-y>",lambda _:self.undo(redo=True))
        self.poll_id=self.after(60,self.poll)

    def _build(self):
        root=ttk.Frame(self,padding=10)
        root.pack(fill="both",expand=True)
        ttk.Label(root,text="DXF → G-code · 2.5D",font=("Segoe UI",19,"bold")).pack(anchor="w")
        ttk.Label(root,text="All dimensions: mm · Feeds: mm/min · G54 work zero · Z=0 at stock top · Experimental, not machine validated").pack(anchor="w",pady=(0,8))
        source=ttk.LabelFrame(root,text="1 · Drawing",padding=6)
        source.pack(fill="x")
        ttk.Entry(source,textvariable=self.dxf).grid(row=0,column=0,columnspan=7,sticky="ew")
        ttk.Button(source,text="Browse…",command=self.browse).grid(row=0,column=7,padx=4)
        ttk.Button(source,text="Load",command=self.load).grid(row=0,column=8)
        source.columnconfigure(0,weight=1)
        for i,(label,var,values) in enumerate((("DXF units",self.source_units,("Auto","mm","inch")),("Scale",self.scale,None),("Curve tolerance",self.tolerance,None),("XY origin",self.origin,("Drawing origin","Lower left")))):
            group=ttk.Frame(source)
            group.grid(row=1,column=2*i,columnspan=2,sticky="w",padx=4,pady=5)
            ttk.Label(group,text=label).pack(side="left",padx=4)
            widget=ttk.Combobox(group,textvariable=var,values=values,state="readonly",width=15) if values else ttk.Entry(group,textvariable=var,width=8)
            widget.pack(side="left")
        panes=ttk.PanedWindow(root,orient="horizontal")
        panes.pack(fill="both",expand=True,pady=8)
        left=ttk.Frame(panes,width=435)
        right=ttk.Frame(panes)
        panes.add(left,weight=0)
        panes.add(right,weight=1)
        scroller=ScrollFrame(left)
        scroller.pack(fill="both",expand=True)
        editor=scroller.body
        ttk.Label(editor,text="2 · Operation",font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=2,sticky="w")
        self.field_widgets={}
        labels=(('name','Name'),('layer','DXF layer (* = all)'),('mode','Operation'),('depth','Final depth below stock top'),('stepdown','Maximum depth per pass'),('tool_diameter','Cutter diameter'),('stepover','Pocket stepover (%)'),('feed','Cutting feed'),('plunge','Plunge feed'),('tabs','Outside holding tabs (0 = off)'),('tab_width','Bridge width'),('tab_height','Tab height above cut bottom'))
        for row,(key,label) in enumerate(labels,1):
            ttk.Label(editor,text=label).grid(row=row,column=0,sticky="w",padx=4,pady=3)
            if key in ("layer","mode"):
                widget=ttk.Combobox(editor,textvariable=self.fields[key],state="readonly",values=("*",) if key=="layer" else MODES,width=21)
                if key=="layer": self.layer_box=widget
            else:
                widget=ttk.Entry(editor,textvariable=self.fields[key],width=23)
            widget.grid(row=row,column=1,sticky="ew",pady=3)
            self.field_widgets[key]=widget
        bar=ttk.Frame(editor)
        bar.grid(row=13,column=0,columnspan=2,sticky="ew",pady=5)
        for label,fn in (("Add",self.add),("Apply",self.update_selected),("Discard edits",self.discard_edits),("Reset tabs",self.reset_tabs)):
            ttk.Button(bar,text=label,command=fn).pack(side="left",padx=2)
        ttk.Label(editor,textvariable=self.pending,foreground="#a14c00",wraplength=400).grid(row=14,column=0,columnspan=2,sticky="w")
        ttk.Label(editor,text="Depth is positive below the stock top. Stepover is path spacing as a percentage of cutter diameter.\nTabs retain material above the final cut bottom.",wraplength=400).grid(row=15,column=0,columnspan=2,sticky="w",pady=7)
        order=ttk.LabelFrame(left,text="3 · Operation order",padding=6)
        order.pack(fill="x",pady=(6,0))
        self.tree=ttk.Treeview(order,columns=("mode","layer","depth"),show="tree headings",height=5,selectmode="browse")
        for key,label,width in (("#0","Name",105),("mode","Operation",110),("layer","Layer",80),("depth","Depth",50)):
            self.tree.heading(key,text=label)
            self.tree.column(key,width=width,minwidth=35)
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>",self.select)
        bar=ttk.Frame(order); bar.pack(fill="x",pady=4)
        for label,fn in (("↑",lambda:self.reorder(-1)),("↓",lambda:self.reorder(1)),("Duplicate",self.duplicate),("Remove",self.remove),("Undo",self.undo),("Redo",lambda:self.undo(True))):
            ttk.Button(bar,text=label,command=fn,width=8 if len(label)>2 else 3).pack(side="left",padx=1)
        bar=ttk.Frame(order);bar.pack(fill="x")
        ttk.Button(bar,text="Open job…",command=self.open_config).pack(side="left")
        ttk.Button(bar,text="Save job…",command=self.save_config).pack(side="left",padx=5)
        book=ttk.Notebook(right); book.pack(fill="both",expand=True)
        self.preview=ToolpathPreview(book,self.move_tab)
        self.canvas=self.preview.canvas
        book.add(self.preview,text="Toolpath / depth preview")
        setup=ScrollFrame(book); book.add(setup,text="Stock & machine setup")
        ttk.Label(setup.body,text="Enter limits in G54 WORK coordinates, not raw machine coordinates.\nDefaults are examples. Confirm them for your zero position, cutter and stock.\nChecks cover cutter envelope and fixture HEIGHT; clamp locations are not modelled.",wraplength=690).grid(row=0,column=0,columnspan=2,sticky="w",pady=10)
        labels={"safe_z":"Safe Z above stock top", "spindle":"Spindle S value", "spindle_on":"Use M3 spindle control", "spindle_delay":"Spindle startup delay (seconds)", "check_setup":"Enable stock / clearance / travel checks", "stock_thickness":"Stock thickness", "spoilboard_allowance":"Allowed cut into spoilboard", "fixture_height":"Highest fixture above stock top", "tool_stickout":"Exposed tool length below collet", "x_min":"G54 X minimum (cutter envelope)","x_max":"G54 X maximum (cutter envelope)","y_min":"G54 Y minimum (cutter envelope)","y_max":"G54 Y maximum (cutter envelope)","z_min":"G54 Z minimum (tool tip)","z_max":"G54 Z maximum (tool tip)"}
        for row,(key,var) in enumerate(self.setup_vars.items(),1):
            if isinstance(var,tk.BooleanVar):
                ttk.Checkbutton(setup.body,text=labels[key],variable=var).grid(row=row,column=0,columnspan=2,sticky="w",pady=5)
            else:
                ttk.Label(setup.body,text=labels[key]).grid(row=row,column=0,sticky="w",padx=8,pady=5)
                ttk.Entry(setup.body,textvariable=var,width=18).grid(row=row,column=1,sticky="w")
        notes=ttk.Frame(book);book.add(notes,text="Job details / warnings")
        self.notes=tk.Text(notes,wrap="word",font=("Segoe UI",10),state="disabled",width=65)
        self.notes.pack(fill="both",expand=True)
        ttk.Label(right,textvariable=self.summary,wraplength=740).pack(fill="x",pady=6)
        actions=ttk.Frame(right);actions.pack(fill="x")
        self.preview_button=ttk.Button(actions,text="Build preview",command=self.build)
        self.preview_button.pack(side="left",fill="x",expand=True)
        self.export_button=ttk.Button(actions,text="Export G-code…",command=self.export,state="disabled")
        self.export_button.pack(side="left",fill="x",expand=True,padx=5)
        self.cancel_button=ttk.Button(actions,text="Cancel",command=self.cancel,state="disabled")
        self.cancel_button.pack(side="left")
        self.progress=ttk.Progressbar(root,mode="indeterminate")
        self.progress.pack(fill="x",pady=4)
        ttk.Label(root,textvariable=self.status,wraplength=1280).pack(anchor="w")

    def signature(self):
        return (self.dxf.get(),self.source_units.get(),self.scale.get(),self.tolerance.get(),self.origin.get())

    def import_config(self):
        return validate_import(dict(source_units=self.source_units.get(),scale=self.scale.get(),tolerance=self.tolerance.get(),origin=self.origin.get()))

    def settings(self):
        result=Settings(**{k:v.get() for k,v in self.setup_vars.items()})
        result.validate()
        return result

    def invalidate(self,*_):
        self.revision+=1
        self.job=None
        self.job_dirty=True
        self.export_button.configure(state="disabled")
        self.summary.set("Settings changed — rebuild preview before export.")
        self.preview.data=None
        if self.loaded_signature != self.signature():
            self.preview.drawing=None
        self.preview.schedule()

    def editor_changed(self,*_):
        if self.editor_loading: return
        self.update_field_states()
        dirty=self.editor_is_dirty()
        self.pending.set("Unapplied changes — Apply or Discard before building/exporting." if dirty else "No pending operation edits")
        self.export_button.configure(state="normal" if self.job and not dirty and not self.busy else "disabled")

    def update_field_states(self):
        mode=self.fields["mode"].get()
        self.field_widgets["stepover"].configure(state="normal" if mode=="Pocket" else "disabled")
        for key in ("tabs","tab_width","tab_height"):
            self.field_widgets[key].configure(state="normal" if mode=="Outside profile" else "disabled")

    def editor_is_dirty(self):
        return {k:v.get() for k,v in self.fields.items()} != self.editor_baseline

    def set_editor(self,index):
        self.editor_loading=True
        self.active_index=index
        op=self.operations[index] if index is not None else Operation()
        data=asdict(op)
        self.custom_tabs=copy.deepcopy(op.tab_positions)
        for k,var in self.fields.items():var.set(str(data[k]))
        self.editor_baseline={k:v.get() for k,v in self.fields.items()}
        self.editor_loading=False
        self.editor_changed()

    def discard_edits(self):
        self.set_editor(self.active_index)

    def resolve_edits(self):
        if not self.editor_is_dirty(): return True
        answer=messagebox.askyesnocancel("Unapplied operation edits","Apply the edited operation?\nYes: apply (or add a new operation).\nNo: discard edits. Cancel: stay here.")
        if answer is None:return False
        if answer:
            return self.update_selected() if self.active_index is not None else self.add()
        self.discard_edits()
        return True

    def read_operation(self):
        data={k:v.get() for k,v in self.fields.items()}
        data["tab_positions"]=copy.deepcopy(self.custom_tabs)
        if data["mode"]!="Outside profile":
            data["tabs"]=0;data["tab_positions"]={}
        op=Operation(**data);op.validate()
        return op

    def snapshot(self):return copy.deepcopy(self.operations)

    def remember(self):
        self.undo_stack.append(self.snapshot());self.undo_stack=self.undo_stack[-50:]
        self.redo_stack.clear()

    def refresh_tree(self,selected=None):
        self.tree.delete(*self.tree.get_children())
        for i,op in enumerate(self.operations):
            self.tree.insert("","end",iid=str(i),text=op.name,values=(op.mode,op.layer,f"{op.depth:g}"))
        self.set_editor(selected)
        if selected is not None:self.tree.selection_set(str(selected))
        self.invalidate()

    def selected_index(self):
        return int(self.tree.selection()[0]) if self.tree.selection() else None

    def select(self,_=None):
        index=self.selected_index()
        if index==self.active_index:return
        if self.busy or not self.resolve_edits():
            if self.active_index is not None:self.tree.selection_set(str(self.active_index))
            else:self.tree.selection_remove(*self.tree.selection())
            return
        self.set_editor(index)

    def add(self):
        if self.busy:return False
        try:
            op=self.read_operation();self.remember();self.operations.append(op)
            self.refresh_tree(len(self.operations)-1);return True
        except Exception as exc:messagebox.showerror("Operation settings",str(exc));return False

    def update_selected(self):
        if self.busy or self.active_index is None:return False
        try:
            op=self.read_operation();self.remember();self.operations[self.active_index]=op
            self.refresh_tree(self.active_index);return True
        except Exception as exc:messagebox.showerror("Operation settings",str(exc));return False

    def remove(self):
        if self.busy or self.active_index is None or not self.resolve_edits():return
        self.remember();self.operations.pop(self.active_index);self.refresh_tree()

    def reorder(self,delta):
        if self.busy or not self.resolve_edits():return
        i=self.active_index
        if i is not None and 0<=i+delta<len(self.operations):
            self.remember();self.operations[i],self.operations[i+delta]=self.operations[i+delta],self.operations[i]
            self.refresh_tree(i+delta)

    def duplicate(self):
        if self.busy or self.active_index is None or not self.resolve_edits():return
        self.remember();op=copy.deepcopy(self.operations[self.active_index]);op.name+=" copy"
        self.operations.append(op);self.refresh_tree(len(self.operations)-1)

    def undo(self,redo=False):
        if self.busy or not self.resolve_edits():return
        source,destination=(self.redo_stack,self.undo_stack) if redo else (self.undo_stack,self.redo_stack)
        if source:
            destination.append(self.snapshot());self.operations=source.pop();self.refresh_tree()

    def reset_tabs(self):
        if self.busy:return
        self.custom_tabs={}
        if self.active_index is not None:
            self.update_selected()

    def move_tab(self,op_index,path_index,tab_index,fraction):
        if self.busy or not self.job or not self.resolve_edits():return
        if self.job is None:return  # Applying edits invalidates the old preview.
        plan=self.job.plans[op_index]
        path=plan.paths[path_index]
        values=list(tab_centres(path,plan.operation));values[tab_index]=fraction
        self.remember()
        self.operations[op_index].tab_positions[contour_key(path)]=values
        self.refresh_tree(op_index)
        self.build()

    def browse(self):
        if self.busy or not self.resolve_edits():return
        filename=filedialog.askopenfilename(filetypes=[("DXF drawings","*.dxf")])
        if filename:self.dxf.set(filename);self.load()

    def start_task(self,kind,fn,on_success):
        if self.busy:return
        self.busy=True
        self.cancel_event=threading.Event()
        self.task_kind=kind;self.task_revision=self.revision;self.on_success=on_success
        self.preview_button.configure(state="disabled");self.export_button.configure(state="disabled")
        self.cancel_button.configure(state="normal");self.progress.start(20)
        self.status.set(kind+"…")
        cancel=self.cancel_event.is_set
        last=[0.0]
        def progress(message,current,total):
            now=time.monotonic()
            if now-last[0]>.08:
                last[0]=now;self.results.put(("progress",message))
        def worker():
            try:self.results.put(("done",fn(cancel,progress)))
            except Exception as exc:self.results.put(("error",exc))
        threading.Thread(target=worker,daemon=True).start()

    def cancel(self):
        self.cancel_event.set();self.status.set("Cancelling at the next processing checkpoint…")

    def poll(self):
        for _ in range(100):
            try:kind,result=self.results.get_nowait()
            except queue.Empty:break
            if kind=="progress":
                if not self.cancel_event.is_set():self.status.set(result+"…")
                continue
            self.busy=False;self.progress.stop()
            self.preview_button.configure(state="normal");self.cancel_button.configure(state="disabled")
            if kind=="error":
                self.status.set(str(result))
                if not isinstance(result,Cancelled):messagebox.showerror(self.task_kind+" failed",str(result))
            elif self.task_kind!="Export" and (self.cancel_event.is_set() or self.revision!=self.task_revision):
                self.status.set("Result discarded because inputs changed or the task was cancelled.")
            else:self.on_success(result)
        self.poll_id=self.after(60,self.poll)

    def load(self):
        if self.busy or not self.resolve_edits():return
        try:config=self.import_config()
        except Exception as exc:messagebox.showerror("Drawing settings",str(exc));return
        path=self.dxf.get();signature=self.signature()
        self.invalidate();self.drawing=None;self.loaded_signature=None
        def work(cancel,progress):
            before=fingerprint(path)
            drawing=load_dxf(path,**config,cancel=cancel,progress=progress)
            if fingerprint(path)!=before:raise CamError("The DXF changed during import. Load it again.")
            return drawing,before
        def done(result):
            self.drawing,self.loaded_hash=result;self.loaded_signature=signature
            self.layer_box.configure(values=("*",*sorted(self.drawing.layers)))
            self.preview.set_drawing(self.drawing)
            x0,y0,x1,y1=self.drawing.bounds
            self.status.set(f"Loaded {len(self.drawing.paths)} paths; {x1-x0:.3f} × {y1-y0:.3f} mm. Add operations, then build preview.")
            self.set_notes(self.status.get()+"\n\n"+"\n".join(self.drawing.warnings))
        self.start_task("Import",work,done)

    def build(self):
        if self.busy or not self.resolve_edits():return
        try:
            config=self.import_config();settings=self.settings();operations=self.snapshot()
            if not operations:raise CamError("Add at least one operation.")
        except Exception as exc:messagebox.showerror("Job settings",str(exc));return
        path=self.dxf.get();signature=self.signature()
        cached=self.drawing if signature==self.loaded_signature else None
        cached_hash=self.loaded_hash
        self.invalidate()
        def work(cancel,progress):
            checksum=fingerprint(path)
            drawing=cached if cached is not None and checksum==cached_hash else load_dxf(path,**config,cancel=cancel,progress=progress)
            job=build_job(drawing,operations,settings,cancel,progress)
            data=prepare_preview(job,cancel)
            if fingerprint(path)!=checksum:raise CamError("The DXF changed during processing. Rebuild the job.")
            return job,data,checksum
        def done(result):
            self.job,data,self.loaded_hash=result
            self.drawing=self.job.drawing;self.loaded_signature=signature
            self.layer_box.configure(values=("*",*sorted(self.drawing.layers)))
            self.preview.drawing=self.drawing;self.preview.set_data(data)
            self.export_button.configure(state="normal" if not self.editor_is_dirty() else "disabled")
            xmin,ymin,xmax,ymax=data.bounds
            depth=max(p.operation.depth for p in self.job.plans)
            tool=self.job.plans[0].operation.tool_diameter
            self.summary.set(f"{self.origin.get()} · Ø{tool:g} mm · lowest Z −{depth:g} mm · XY centres {xmin:.2f},{ymin:.2f} to {xmax:.2f},{ymax:.2f}\n{len(self.job.moves)} moves · {len(self.job.warnings)} notices · setup checks {'ON' if settings.check_setup else 'OFF'}")
            details=["EXPERIMENTAL — NOT MACHINE VALIDATED",self.summary.get(),"", "Direct plunge entries. No fixture-position or stock-removal simulation.",""]
            for i,plan in enumerate(self.job.plans):
                op=plan.operation
                details.append(f"{i+1}. {op.name} — {op.mode}; layer {op.layer}; final Z {-op.depth:g}; stepdown {op.stepdown:g}; feed {op.feed:g}; plunge {op.plunge:g}")
            details.extend(["","NOTICES / WARNINGS",*self.job.warnings])
            self.set_notes("\n".join(details));self.status.set("Preview ready. Review depths, cutter envelope, tab positions and notices before export.")
        self.start_task("Build",work,done)

    def set_notes(self,text):
        self.notes.configure(state="normal");self.notes.delete("1.0","end");self.notes.insert("1.0",text);self.notes.configure(state="disabled")

    def export(self):
        if self.busy or not self.resolve_edits() or not self.job:return
        if self.job.warnings and not messagebox.askokcancel("Review job notices","\n\n".join(self.job.warnings)+"\n\nExport for review?"):return
        filename=filedialog.asksaveasfilename(initialfile=Path(self.dxf.get()).stem+".gcode",defaultextension=".gcode",filetypes=[("G-code","*.gcode")])
        if not filename:return
        paths=export_paths(filename)
        recovery=transaction_dir(paths[0]).exists()
        if recovery and not messagebox.askyesno("Recover interrupted export","Restore the previous file set from the interrupted export, then export this job? Do not continue if another instance is currently exporting this target."):return
        if any(p.exists() for p in paths[1:]) and not messagebox.askokcancel("Replace companion files","The matching preview/report files already exist and will be replaced with this export. Continue?"):return
        job=self.job;expected_hash=self.loaded_hash
        def work(cancel,progress):
            if fingerprint(job.drawing.source)!=expected_hash:raise CamError("The drawing changed since preview. Rebuild before exporting.")
            if recovery:recover_export(filename)
            export_job(job,filename,cancel,progress)
            return filename
        def done(filename):
            self.status.set(f"Exported {filename}, preview and report. Simulate and air cut before machining.")
            self.export_button.configure(state="normal" if self.job and not self.editor_is_dirty() else "disabled")
        self.start_task("Export",work,done)

    def save_config(self):
        if self.busy or not self.resolve_edits():return False
        try:
            imports=self.import_config();settings=self.settings()
            filename=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("Job settings","*.json")])
            if not filename:return False
            save_config(filename,imports,settings,self.operations,self.dxf.get(),self.active_index)
            self.job_dirty=False;self.status.set("Job saved with drawing reference and fingerprint.");return True
        except Exception as exc:messagebox.showerror("Cannot save job",str(exc));return False

    def open_config(self):
        if self.busy or not self.resolve_edits():return
        filename=filedialog.askopenfilename(filetypes=[("Job settings","*.json")])
        if not filename:return
        try:
            config=read_config(filename)  # Validate the entire model before mutation.
            if config.drawing:
                if not Path(config.drawing).is_file():
                    raise CamError("The job's drawing is missing. Move the DXF back beside the job or update its drawing path.")
                if config.drawing_sha256 and fingerprint(config.drawing)!=config.drawing_sha256:
                    if not messagebox.askyesno("Drawing changed","The drawing differs from the saved fingerprint. Open these settings and rebuild against the changed drawing?"):return
            self.remember();self.operations=config.operations
            for k,var in (("source_units",self.source_units),("scale",self.scale),("tolerance",self.tolerance),("origin",self.origin)):
                var.set(str(config.import_settings[k]))
            for k,v in asdict(config.settings).items():self.setup_vars[k].set(v)
            if config.drawing:self.dxf.set(config.drawing)
            self.refresh_tree(config.selected_operation)
            self.job_dirty=False
            self.status.set("Job opened. Build preview to load/recheck the drawing and setup.")
        except Exception as exc:messagebox.showerror("Cannot open job",str(exc))

    def close(self):
        if self.busy:
            self.cancel();messagebox.showinfo("Task running","Cancellation requested. Wait for it to finish before closing.");return
        if not self.resolve_edits():return
        if self.job_dirty:
            answer=messagebox.askyesnocancel("Unsaved job","Save the job settings before closing?")
            if answer is None or (answer and not self.save_config()):return
        self.destroy()

    def destroy(self):
        self.cancel_event.set()
        if hasattr(self,"poll_id"):self.after_cancel(self.poll_id)
        super().destroy()
