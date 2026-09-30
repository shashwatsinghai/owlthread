"""Small Tk animations scheduled exclusively on the UI thread."""
from __future__ import annotations
import logging
import time
import tkinter as tk
from typing import Callable
logger = logging.getLogger(__name__)


class Animator:
    @staticmethod
    def ease_in_out(t: float) -> float:
        return 4*t*t*t if t<0.5 else 1-(-2*t+2)**3/2

    @staticmethod
    def _animate(widget: tk.Misc, duration_ms: int, step: Callable[[float],None],
                 callback: Callable[[],None] | None = None) -> None:
        start = time.monotonic()
        if not hasattr(widget,"_owlthread_animation_ids"):
            widget._owlthread_animation_ids = set()
            def cancel(event: tk.Event) -> None:
                if event.widget is widget:
                    for task in list(widget._owlthread_animation_ids):
                        try: widget.after_cancel(task)
                        except tk.TclError: pass
                    widget._owlthread_animation_ids.clear()
            widget.bind("<Destroy>",cancel,add="+")
        scheduled: str | None = None
        def tick() -> None:
            nonlocal scheduled
            if scheduled:
                widget._owlthread_animation_ids.discard(scheduled)
                scheduled=None
            try:
                if not widget.winfo_exists():
                    return
                progress = min(1,(time.monotonic()-start)*1000/max(1,duration_ms))
                step(Animator.ease_in_out(progress))
                if progress<1:
                    scheduled=widget.after(16,tick)
                    widget._owlthread_animation_ids.add(scheduled)
                elif callback:
                    callback()
            except tk.TclError:
                logger.debug("Animation target was closed")
        tick()

    @staticmethod
    def fade_in(widget: tk.Misc, duration_ms: int = 300) -> None:
        if isinstance(widget,(tk.Tk,tk.Toplevel)):
            widget.attributes("-alpha",0)
            Animator._animate(widget,duration_ms,lambda t:widget.attributes("-alpha",t))

    @staticmethod
    def fade_out(widget: tk.Misc, duration_ms: int = 300, callback: Callable[[],None] | None = None) -> None:
        if isinstance(widget,(tk.Tk,tk.Toplevel)):
            Animator._animate(widget,duration_ms,lambda t:widget.attributes("-alpha",1-t),callback)

    @staticmethod
    def slide_in(widget: tk.Widget, direction: str = "bottom", distance: int = 20, duration_ms: int = 400) -> None:
        info = widget.place_info()
        if not info:
            return
        axis = "x" if direction in {"left","right"} else "y"
        target = float(info.get(axis,0))
        sign = -1 if direction in {"left","top"} else 1
        Animator._animate(widget,duration_ms,lambda t:widget.place_configure(**{axis:target+sign*distance*(1-t)}))

    @staticmethod
    def pulse(widget: tk.Widget, color_from: str, color_to: str, duration_ms: int = 600) -> None:
        a = tuple(int(color_from[i:i+2],16) for i in (1,3,5))
        b = tuple(int(color_to[i:i+2],16) for i in (1,3,5))
        def step(t: float) -> None:
            ratio = 1-abs(2*t-1)
            widget.configure(bg="#"+"".join(f"{round(x+(y-x)*ratio):02x}" for x,y in zip(a,b)))
        Animator._animate(widget,duration_ms,step)
