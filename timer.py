#!/usr/bin/env python3
"""Таймер.

Окно вызывается по SUPER+SHIFT+T, ставится время — кнопкой или любое, до
секунды, в колёсиках «ч / мин / сек», — и оно уходит с глаз, но продолжает
считать. Это главное решение здесь: закрытое окно у таймера
обычно значит «отменил», а хочется наоборот — поставил и забыл.

Вид взят у системы: «Monochrome Vivid» из ~/.config/hypr/colors.conf. Ни
одного цвета; то, что идёт, и то, что кончилось, различаются яркостью и
толщиной кольца, а не краской.
"""

import math
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

APP_ID = "dev.bogdan.Timer"
STATE = Path.home() / ".local/state/timer"

# Кнопки быстрого выбора. Пять штук, а не десять: список, в котором надо
# искать глазами, медленнее, чем «+5» нажатое дважды.
PRESETS = [1, 5, 10, 15, 25, 45]

# Потолок колёсика часов. Больше суток таймер ставят разве что по ошибке, а
# две цифры помещаются в кольцо.
MAX_HOURS = 99

ALARM = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"

CSS = """
window, .root { background: #090909; }
.digits {
    font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace;
    font-size: 40px;
    font-weight: bold;
    color: #ffffff;
}
/* С часами цифр восемь, и в кольцо 40px не влезает. */
.digits.long { font-size: 30px; }
.caption { color: #737373; font-size: 12px; }
.done .digits { color: #ffffff; }
button {
    background: #1a1a1a;
    color: #b0b0b0;
    border: 1px solid #333333;
    border-radius: 10px;
    padding: 7px 0;
    font-size: 13px;
    font-weight: bold;
    text-shadow: none;
}
button:hover { background: #242424; color: #ffffff; }
button.chosen { color: #ffffff; border-color: #ffffff; }
button.go { background: #ffffff; color: #000000; border-color: #ffffff; }
button.go:hover { background: #e6e6e6; }
/* Явно, потому что свои цвета выше перебивают штатное затемнение GTK, и
   «Пуск» выглядел нажимаемым, когда время ещё не выбрано. */
button:disabled { background: #141414; color: #4a4a4a; border-color: #242424; }
button.go:disabled { background: #2a2a2a; color: #5a5a5a; border-color: #2a2a2a; }

/* Колёсики «ч / мин / сек». Вертикальные: + сверху, − снизу, как у часов,
   и не надо искать мелкие кнопки справа от поля. */
spinbutton {
    background: #1a1a1a;
    color: #ffffff;
    border: 1px solid #333333;
    border-radius: 10px;
}
spinbutton entry, spinbutton text {
    background: transparent;
    color: #ffffff;
    border: none;
    box-shadow: none;
    font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace;
    font-size: 20px;
    font-weight: bold;
    padding: 2px 0;
}
/* .vertical и :last-child — чтобы перебить тему: она красит нижнюю кнопку
   в свою подложку. */
spinbutton.vertical button, spinbutton.vertical button:last-child {
    background: transparent;
    border: none;
    box-shadow: none;
    border-radius: 10px;
    padding: 2px 0;
    color: #737373;
}
spinbutton selection, spinbutton text selection, spinbutton entry selection {
    background: #ffffff;
    color: #000000;
}
spinbutton.vertical button:hover { background: #242424; color: #ffffff; }
spinbutton:disabled { background: #141414; border-color: #242424; }
spinbutton:disabled entry, spinbutton:disabled text { color: #4a4a4a; }
spinbutton.vertical:disabled button { background: transparent; color: #2a2a2a; }
"""


def say(title: str, body: str) -> None:
    """Уведомление. Без него таймер бесполезен, когда окно спрятано."""
    subprocess.Popen(
        ["notify-send", "-a", "Таймер", "-u", "critical", title, body],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ring() -> None:
    if Path(ALARM).exists():
        subprocess.Popen(
            ["paplay", ALARM], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 14:
        return many
    tail = n % 10
    if tail == 1:
        return one
    if tail in (2, 3, 4):
        return few
    return many


def spell(seconds: int) -> str:
    """«5 минут», «1 ч 30 мин», «45 секунд» — для уведомления, а не для циферблата.

    Секунды называются, только пока нет часов: «2 ч 0 мин 5 с» уже шум.
    """
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        out = f"{hours} ч"
        return out if not minutes else f"{out} {minutes} мин"
    if not minutes:
        return f"{secs} {plural(secs, 'секунда', 'секунды', 'секунд')}"
    out = f"{minutes} {plural(minutes, 'минута', 'минуты', 'минут')}"
    return out if not secs else f"{minutes} мин {secs} с"


def clock(seconds: int) -> str:
    """Циферблат: 04:56, а с часами — 1:30:00."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def wheel(upper: int) -> Gtk.SpinButton:
    spin = Gtk.SpinButton.new_with_range(0, upper, 1)
    spin.set_orientation(Gtk.Orientation.VERTICAL)
    spin.set_numeric(True)
    spin.set_width_chars(2)
    spin.set_alignment(0.5)
    # Ведущий ноль: «05», а не «5», — колёсики читаются как часы.
    spin.connect("output", lambda s: s.set_text(f"{int(s.get_value()):02d}") or True)
    # Поле при фокусе выделяется целиком: набранное «7» заменяет «00», а не
    # дописывается к нему в «700». Через idle — иначе GTK сам снимет выделение
    # сразу после фокуса.
    spin.connect(
        "focus-in-event",
        lambda s, _e: GLib.idle_add(lambda: s.select_region(0, -1) and False) and False,
    )
    return spin


class Dial(Gtk.DrawingArea):
    """Кольцо, которое убывает.

    Рисуется вручную, потому что ничего похожего в GTK нет, а полоска прогресса
    во всю ширину окна читается как загрузка файла, а не как оставшееся время.
    """

    def __init__(self):
        super().__init__()
        self.fraction = 1.0
        self.set_size_request(210, 210)
        self.connect("draw", self._draw)

    def _draw(self, _widget, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        size = min(width, height)
        cx, cy = width / 2, height / 2
        radius = size / 2 - 10

        cr.set_line_width(6)
        cr.set_line_cap(1)  # round

        # Дорожка: показывает, сколько кольца всего, иначе в конце непонятно,
        # много прошло или мало осталось.
        cr.set_source_rgb(0.16, 0.16, 0.16)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        if self.fraction > 0:
            cr.set_source_rgb(1, 1, 1)
            start = -math.pi / 2
            cr.arc(cx, cy, radius, start, start + 2 * math.pi * self.fraction)
            cr.stroke()
        return False


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Таймер")
        self.set_default_size(300, -1)
        self.set_resizable(False)

        self.total = 0          # сколько поставили, в секундах
        self.ends_at = 0.0      # момент окончания, монотонные часы
        self.left = 0           # остаток на паузе
        self.running = False
        self.tick = None
        # Колёсики двигает и сам код (кнопки быстрого выбора, «Сброс»); тогда
        # их сигнал не должен снова ставить время.
        self.syncing = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.get_style_context().add_class("root")
        root.set_border_width(18)
        self.add(root)

        self.dial = Dial()
        overlay = Gtk.Overlay()
        overlay.add(self.dial)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_halign(Gtk.Align.CENTER)
        text.set_valign(Gtk.Align.CENTER)
        self.digits = Gtk.Label(label="00:00")
        self.digits.get_style_context().add_class("digits")
        self.caption = Gtk.Label(label="выбери время")
        self.caption.get_style_context().add_class("caption")
        text.pack_start(self.digits, False, False, 0)
        text.pack_start(self.caption, False, False, 0)
        overlay.add_overlay(text)
        root.pack_start(overlay, False, False, 0)

        wheels = Gtk.Box(spacing=8, homogeneous=True)
        self.hours = wheel(MAX_HOURS)
        self.minutes = wheel(59)
        self.seconds = wheel(59)
        for spin, unit in (
            (self.hours, "ч"),
            (self.minutes, "мин"),
            (self.seconds, "сек"),
        ):
            spin.connect("value-changed", self.on_wheel)
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            column.pack_start(spin, False, False, 0)
            label = Gtk.Label(label=unit)
            label.get_style_context().add_class("caption")
            column.pack_start(label, False, False, 0)
            wheels.pack_start(column, True, True, 0)
        root.pack_start(wheels, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        self.preset_buttons = {}
        for i, minutes in enumerate(PRESETS):
            button = Gtk.Button(label=str(minutes))
            button.connect("clicked", self.on_preset, minutes)
            grid.attach(button, i % 3, i // 3, 1, 1)
            self.preset_buttons[minutes] = button
        root.pack_start(grid, False, False, 0)

        row = Gtk.Box(spacing=8, homogeneous=True)
        self.go = Gtk.Button(label="Пуск")
        self.go.get_style_context().add_class("go")
        self.go.connect("clicked", self.on_go)
        self.stop = Gtk.Button(label="Сброс")
        self.stop.connect("clicked", self.on_reset)
        row.pack_start(self.go, True, True, 0)
        row.pack_start(self.stop, True, True, 0)
        root.pack_start(row, False, False, 0)

        self.minutes.grab_focus()
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_close)
        self.render()

    # ---- время ----

    def remaining(self) -> int:
        if self.running:
            return max(0, round(self.ends_at - time.monotonic()))
        return self.left

    def render(self):
        left = self.remaining()
        self.digits.set_text(clock(left))
        digits = self.digits.get_style_context()
        if left >= 3600:
            digits.add_class("long")
        else:
            digits.remove_class("long")
        self.dial.fraction = (left / self.total) if self.total else 0.0
        self.dial.queue_draw()

        # «Пауза» только когда время действительно кто-то тронул. Сразу после
        # выбора кнопки отсчёт ещё не начинался, и слово «пауза» там врёт.
        if self.running:
            self.caption.set_text("идёт")
        elif self.total and left == 0:
            self.caption.set_text("готово")
        elif self.left and self.left < self.total:
            self.caption.set_text("пауза")
        elif self.left:
            self.caption.set_text("пробел или «Пуск»")
        else:
            self.caption.set_text("выбери время")

        self.go.set_label("Пауза" if self.running else "Пуск")
        # После «готово» колёсики всё ещё показывают время, и «Пуск» ставит
        # его заново — не надо трогать колёсико, чтобы повторить.
        self.go.set_sensitive(
            bool(self.left) or self.running or bool(self.wheels_total())
        )
        # На ходу колёсики заперты: случайный скролл над ними иначе сбил бы
        # идущий отсчёт.
        for spin in (self.hours, self.minutes, self.seconds):
            spin.set_sensitive(not self.running)
        for minutes, button in self.preset_buttons.items():
            state = button.get_style_context()
            if self.total == minutes * 60:
                state.add_class("chosen")
            else:
                state.remove_class("chosen")

    def on_tick(self):
        self.render()
        if self.remaining() <= 0:
            self.finish()
            return False
        return True

    def finish(self):
        self.running = False
        self.left = 0
        self.tick = None
        self.render()
        ring()
        # Без глагола: «1 минута прошло» и «1 минуту прошла» одинаково плохи,
        # а согласовывать род ради строки из двух слов не стоит.
        say("Время вышло", spell(self.total))
        # Окно показывается само: таймер, о котором не узнал, — не таймер.
        self.present()

    # ---- кнопки ----

    def on_preset(self, _button, minutes):
        self.set_time(minutes * 60)

    def set_time(self, seconds: int, from_wheels: bool = False):
        self.pause()
        self.total = seconds
        self.left = seconds
        if not from_wheels:
            self.show_on_wheels(seconds)
        self.render()

    def show_on_wheels(self, seconds: int):
        hours, rest = divmod(seconds, 3600)
        self.syncing = True
        try:
            self.hours.set_value(hours)
            self.minutes.set_value(rest // 60)
            self.seconds.set_value(rest % 60)
        finally:
            self.syncing = False

    def wheels_total(self) -> int:
        return (
            self.hours.get_value_as_int() * 3600
            + self.minutes.get_value_as_int() * 60
            + self.seconds.get_value_as_int()
        )

    def on_wheel(self, _spin):
        if self.syncing:
            return
        self.set_time(self.wheels_total(), from_wheels=True)

    def on_wheel_enter(self, spin):
        # Сначала принять набранное (иначе GTK применит его только при уходе
        # фокуса), потом пуск.
        if self.running:
            return
        spin.update()
        self.start()

    def on_go(self, _button):
        if self.running:
            self.pause()
        else:
            self.start()

    def start(self):
        if not self.left:
            self.set_time(self.wheels_total(), from_wheels=True)
        if not self.left:
            return
        self.ends_at = time.monotonic() + self.left
        self.running = True
        if self.tick is None:
            self.tick = GLib.timeout_add(200, self.on_tick)
        self.render()

    def pause(self):
        if not self.running:
            return
        self.left = self.remaining()
        self.running = False
        if self.tick is not None:
            GLib.source_remove(self.tick)
            self.tick = None
        self.render()

    def on_reset(self, _button):
        self.set_time(0)

    def on_key(self, _widget, event):
        name = Gdk.keyval_name(event.keyval)
        if name == "Escape":
            self.on_close(None, None)
            return True
        focus = self.get_focus()
        typing = isinstance(focus, Gtk.SpinButton)
        if name == "space":
            # Набранное в колёсике сначала принять, иначе пуск возьмёт
            # прежнее значение.
            if typing and not self.running:
                focus.update()
            self.on_go(None)
            return True
        # Enter в колёсике — пуск. Ловится здесь: сигнал activate у
        # SpinButton в GTK3 по Enter не приходит.
        if name in ("Return", "KP_Enter") and typing:
            self.on_wheel_enter(focus)
            return True
        return False

    def on_close(self, _widget, _event):
        """Закрытие прячет окно, если таймер идёт, и гасит приложение, если нет.

        Ради этого всё и затевалось: поставил и убрал с глаз. Уничтожить окно
        нельзя — GTK тогда снимет и приложение вместе с отсчётом.
        """
        if self.running:
            self.hide()
            say("Таймер идёт", f"Осталось {spell(self.remaining())}")
        else:
            self.get_application().quit()
        return True


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        # Второй запуск не поднимает второй таймер, а показывает первый:
        # ради этого приложение и сделано одноэкземплярным.
        if self.window is None:
            self.window = Window(self)
        self.window.show_all()
        self.window.present()


if __name__ == "__main__":
    STATE.mkdir(parents=True, exist_ok=True)
    # Имя окна задаётся явно: под Wayland GTK берёт app_id отсюда, и правило
    # в hyprland.conf должно на что-то опираться. Иначе класс — «timer.py»
    # или «python3», в зависимости от того, как запустили.
    GLib.set_prgname("timer")
    sys.exit(App().run(sys.argv))
