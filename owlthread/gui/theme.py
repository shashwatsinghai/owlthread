"""Rounded desktop surfaces that retain native Tk keyboard and button behavior."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable
from PIL import Image, ImageDraw, ImageTk

BG = "#101217"
SIDEBAR = "#15181f"
CARD = "#1d212b"
SURFACE = "#2a2e3b"
BORDER = "#343a49"
TEXT = "#f1f2f7"
MUTED = "#a1a9bb"
ACCENT = "#b6a4ff"
SELECTED = "#302c45"


def _surface(width: int, height: int, radius: int, outer: str, fill: str,
             outline: str | None = None) -> Image.Image:
    scale = 3
    image = Image.new("RGB",(width*scale,height*scale),outer)
    ImageDraw.Draw(image).rounded_rectangle(
        (0,0,width*scale-1,height*scale-1),radius=radius*scale,
        fill=fill,outline=outline,width=scale if outline else 1,
    )
    return image.resize((width,height),Image.Resampling.LANCZOS)


class RoundedButton(tk.Button):
    """Native button with an antialiased face, hover, disabled and focus states."""
    def __init__(self, master: tk.Misc, text: str, command: Callable,
                 primary: bool = False) -> None:
        self._face = ACCENT if primary else SURFACE
        self._hover_face = "#cabaff" if primary else "#383d4d"
        self._outer = master.cget("bg")
        self._padx, self._pady = 18, 10
        self._hovered = False
        self._focused = False
        self._paint_key = None
        self._photo = None
        super().__init__(master,text=text,command=command,font=("Segoe UI",10,"bold"),
                         bg=self._outer,fg="#181321" if primary else TEXT,
                         activebackground=self._outer,activeforeground="#181321" if primary else TEXT,
                         disabledforeground="#8991a3",relief="flat",bd=0,highlightthickness=0,
                         padx=0,pady=0,compound="center",cursor="hand2",takefocus=True)
        self._measure()
        self.bind("<Configure>",lambda _:self._paint())
        self.bind("<Enter>",lambda _:self._state(hover=True))
        self.bind("<Leave>",lambda _:self._state(hover=False))
        self.bind("<FocusIn>",lambda _:self._state(focus=True))
        self.bind("<FocusOut>",lambda _:self._state(focus=False))
        self.bind("<Return>",lambda _:self.invoke())
        self._paint()

    def _measure(self) -> None:
        font = tkfont.Font(self,font=super().cget("font"))
        text = super().cget("text")
        self._natural_size = (max(font.measure(line) for line in text.split("\n"))+self._padx*2,
                              font.metrics("linespace")*len(text.split("\n"))+self._pady*2)
        super().configure(width=self._natural_size[0],height=self._natural_size[1])

    def _state(self, *, hover: bool | None = None, focus: bool | None = None) -> None:
        if hover is not None: self._hovered = hover
        if focus is not None: self._focused = focus
        self._paint()

    def _paint(self) -> None:
        width = self.winfo_width() if self.winfo_width()>1 else self._natural_size[0]
        height = self.winfo_height() if self.winfo_height()>1 else self._natural_size[1]
        disabled = super().cget("state") == "disabled"
        face = SURFACE if disabled else self._hover_face if self._hovered else self._face
        outline = ACCENT if self._focused and not disabled else None
        key = (width,height,face,outline,self._outer,disabled,super().cget("text"),super().cget("font"))
        if key == self._paint_key: return
        self._paint_key = key
        self._photo = ImageTk.PhotoImage(_surface(width,height,12,self._outer,face,outline),master=self)
        super().configure(image=self._photo)

    def configure(self, cnf=None, **kwargs):
        if cnf: kwargs.update(cnf)
        if not kwargs: return super().configure()
        if "bg" in kwargs: self._face=kwargs.pop("bg")
        if "background" in kwargs: self._face=kwargs.pop("background")
        if "activebackground" in kwargs: self._hover_face=kwargs.pop("activebackground")
        measure = any(key in kwargs for key in ("font","text","padx","pady"))
        if "padx" in kwargs: self._padx=kwargs.pop("padx")
        if "pady" in kwargs: self._pady=kwargs.pop("pady")
        result = super().configure(**kwargs)
        if measure: self._measure()
        self._paint()
        return result

    config = configure

    def cget(self, key):
        if key in {"bg","background"}: return self._face
        return super().cget(key)


def button(master: tk.Misc, text: str, command: Callable, primary: bool = False) -> RoundedButton:
    return RoundedButton(master,text,command,primary)


class RoundedFrame(tk.Frame):
    """Native container with antialiased corners; children keep standard geometry."""
    def __init__(self, master: tk.Misc, *, bg: str = CARD, radius: int = 18, **kwargs) -> None:
        kwargs.pop("highlightthickness",None)
        kwargs.pop("highlightbackground",None)
        super().__init__(master,bg=bg,highlightthickness=0,bd=0,**kwargs)
        self._radius = radius
        self._outer = master.cget("bg")
        self._corners = []
        self._corner_photos = []
        for anchor in ("nw","ne","sw","se"):
            corner=tk.Label(self,bd=0,highlightthickness=0,bg=self._outer)
            corner.place(relx=1 if "e" in anchor else 0,rely=1 if "s" in anchor else 0,
                         anchor=anchor,width=radius,height=radius,bordermode="outside")
            self._corners.append(corner)
        self._paint_corners()

    def _paint_corners(self) -> None:
        radius=self._radius
        full=_surface(radius*2,radius*2,radius,self._outer,self.cget("bg"))
        self._corner_photos=[]
        for corner,(x,y) in zip(self._corners,((0,0),(radius,0),(0,radius),(radius,radius))):
            photo=ImageTk.PhotoImage(full.crop((x,y,x+radius,y+radius)),master=self)
            self._corner_photos.append(photo)
            corner.configure(image=photo)
            corner.lift()

    def configure(self, cnf=None, **kwargs):
        if cnf: kwargs.update(cnf)
        kwargs.pop("highlightbackground",None)
        result=super().configure(**kwargs)
        if "bg" in kwargs and hasattr(self,"_corners"): self._paint_corners()
        return result

    config = configure


class SegmentedTabs(tk.Frame):
    """A compact, rounded section selector with keyboard-accessible buttons."""
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master,bg=BG)
        self._bar=RoundedFrame(self,bg=SIDEBAR,radius=16,padx=6,pady=6)
        self._bar.pack(fill="x",pady=(0,8))
        self._panes=[]
        self._buttons=[]
        self._selected=0

    def add(self, frame: tk.Frame, *, text: str) -> None:
        index=len(self._panes)
        self._panes.append(frame)
        control=button(self._bar,text,lambda:self.select(index))
        control.configure(bg=SIDEBAR,font=("Segoe UI",10),pady=8)
        control.pack(side="left",fill="x",expand=True,padx=2)
        control.bind("<Left>",lambda _:self._step(-1))
        control.bind("<Right>",lambda _:self._step(1))
        self._buttons.append(control)
        if index == 0: self.select(0)

    def _step(self, amount: int) -> str:
        self.select((self._selected+amount)%len(self._panes))
        self._buttons[self._selected].focus_set()
        return "break"

    def select(self, index: int | None = None):
        if index is None: return str(self._panes[self._selected])
        self._selected=index
        for number,(frame,control) in enumerate(zip(self._panes,self._buttons)):
            control.configure(bg=SELECTED if number==index else SIDEBAR,
                              fg=TEXT if number==index else MUTED)
            if number == index: frame.pack(fill="both",expand=True)
            else: frame.pack_forget()
