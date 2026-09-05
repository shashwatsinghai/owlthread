"""OwlThread Animation Engine — Smooth transitions for CustomTkinter widgets.

Provides reusable animation primitives using tkinter's after() scheduler
for buttery-smooth UI transitions without external dependencies.
"""

import math
from typing import Callable, Optional, Tuple


def _normalize_color(c: Any, fallback: str = "#050810") -> str:
    """Normalize a color to a 6-character hex string (#rrggbb)."""
    if isinstance(c, (list, tuple)):
        c = c[1] if len(c) > 1 else c[0]
    if not isinstance(c, str):
        return fallback
    c_str = c.strip()
    if c_str.lower() == "transparent" or not c_str.startswith("#"):
        return fallback
    h = c_str.lstrip("#")
    if len(h) == 3:
        return f"#{h[0]*2}{h[1]*2}{h[2]*2}"
    if len(h) == 6:
        return f"#{h}"
    return fallback


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color string to RGB tuple, with safe fallback."""
    clean = _normalize_color(hex_color).lstrip("#")
    try:
        return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
    except Exception:
        return (5, 8, 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB values to hex color string."""
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp_color(c1: str, c2: str, t: float) -> str:
    """Linearly interpolate between two hex colors. t=0 returns c1, t=1 returns c2."""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return _rgb_to_hex(
        max(0, min(255, r)),
        max(0, min(255, g)),
        max(0, min(255, b)),
    )


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out: fast start, gentle landing."""
    return 1.0 - (1.0 - t) ** 3


def ease_out_quart(t: float) -> float:
    """Quartic ease-out: even smoother deceleration."""
    return 1.0 - (1.0 - t) ** 4


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out: smooth acceleration and deceleration."""
    if t < 0.5:
        return 4.0 * t * t * t
    else:
        return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


class AnimationEngine:
    """Smooth animation system using tkinter's after() scheduler.

    All animations are non-blocking and use the widget's own event loop.
    Multiple animations can run concurrently on different widgets.
    """

    @staticmethod
    def color_transition(
        widget,
        prop: str,
        from_color: str,
        to_color: str,
        duration_ms: int = 250,
        steps: int = 14,
        easing=ease_out_cubic,
        on_complete: Optional[Callable] = None,
    ) -> None:
        """Smoothly interpolate a widget's color property (fg_color, border_color, text_color).

        Args:
            widget: CustomTkinter widget
            prop: Property name ('fg_color', 'border_color', 'text_color')
            from_color: Starting hex color
            to_color: Target hex color
            duration_ms: Total animation duration in milliseconds
            steps: Number of interpolation frames
            easing: Easing function (default: ease_out_cubic)
            on_complete: Optional callback fired when animation finishes
        """
        if from_color == to_color:
            if on_complete:
                on_complete()
            return

        interval = max(1, duration_ms // steps)

        def _step(i: int) -> None:
            if i > steps:
                try:
                    widget.configure(**{prop: to_color})
                except Exception:
                    pass
                if on_complete:
                    on_complete()
                return
            t = easing(i / steps)
            color = _lerp_color(from_color, to_color, t)
            try:
                widget.configure(**{prop: color})
                widget.after(interval, lambda: _step(i + 1))
            except Exception:
                pass  # Widget was destroyed

        _step(0)

    @staticmethod
    def animate_counter(
        widget,
        from_val: int,
        to_val: int,
        duration_ms: int = 400,
        steps: int = 16,
        easing=ease_out_quart,
        formatter: Optional[Callable[[int], str]] = None,
    ) -> None:
        """Animate a label's text as a smoothly counting number.

        Args:
            widget: CTkLabel widget
            from_val: Starting integer value
            to_val: Target integer value
            duration_ms: Total animation duration
            steps: Number of intermediate frames
            easing: Easing function
            formatter: Optional function to format the number (e.g., add commas)
        """
        if from_val == to_val:
            return

        fmt = formatter or str
        interval = max(1, duration_ms // steps)
        delta = to_val - from_val

        def _step(i: int) -> None:
            if i > steps:
                try:
                    widget.configure(text=fmt(to_val))
                except Exception:
                    pass
                return
            t = easing(i / steps)
            current = int(from_val + delta * t)
            try:
                widget.configure(text=fmt(current))
                widget.after(interval, lambda: _step(i + 1))
            except Exception:
                pass

        _step(0)

    @staticmethod
    def staggered_fade_in(
        widgets: list,
        stagger_ms: int = 40,
        duration_ms: int = 200,
        steps: int = 10,
    ) -> None:
        """Fade in a list of widgets with staggered delay for a cascade effect.

        Uses opacity simulation via fg_color interpolation from bg to target.
        """
        for idx, widget in enumerate(widgets):
            delay = idx * stagger_ms
            try:
                target_color = widget.cget("fg_color")
                if isinstance(target_color, (list, tuple)):
                    target_color = target_color[1] if len(target_color) > 1 else target_color[0]

                # Store widget's original color, start from darker
                bg_start = "#06080d"

                def _do_fade(w=widget, tc=target_color):
                    AnimationEngine.color_transition(
                        w, "fg_color", bg_start, tc,
                        duration_ms=duration_ms, steps=steps
                    )

                widget.after(delay, _do_fade)
            except Exception:
                pass

    @staticmethod
    def pulse_glow(
        widget,
        base_color: str,
        glow_color: str,
        duration_ms: int = 800,
        prop: str = "border_color",
    ) -> None:
        """Single pulse glow animation: base -> glow -> base.

        Great for attention-drawing effects on new data arrival.
        """
        half = duration_ms // 2
        AnimationEngine.color_transition(
            widget, prop, base_color, glow_color,
            duration_ms=half, steps=10,
            on_complete=lambda: AnimationEngine.color_transition(
                widget, prop, glow_color, base_color,
                duration_ms=half, steps=10,
            )
        )

    @staticmethod
    def slide_in_vertical(
        widget,
        distance: int = 20,
        duration_ms: int = 250,
        steps: int = 12,
        easing=ease_out_cubic,
    ) -> None:
        """Simulate a vertical slide-in by adjusting padding.

        Note: True position animation is limited in tkinter grid/pack layouts,
        so we simulate slide-in by animating top padding from large to normal.
        """
        interval = max(1, duration_ms // steps)

        def _step(i: int) -> None:
            if i > steps:
                try:
                    widget.configure(pady=0)
                except Exception:
                    pass
                return
            t = easing(i / steps)
            offset = int(distance * (1.0 - t))
            try:
                widget.configure(pady=(offset, 0))
                widget.after(interval, lambda: _step(i + 1))
            except Exception:
                pass

        _step(0)


# Convenience aliases
fade_color = AnimationEngine.color_transition
count_up = AnimationEngine.animate_counter
cascade_in = AnimationEngine.staggered_fade_in
pulse = AnimationEngine.pulse_glow
