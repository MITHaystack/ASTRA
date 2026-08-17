from contextlib import contextmanager
from pathlib import Path

from nicegui import ui
from .links import MARIMO_URL, STELLARIUM_URL, ASTROMETRY_URL, DOCS_URL, LESSONS_URL, HELP_URL, ABOUT_URL, LICENSE_URL, HAYSTACK_URL

COLORS = {
    "primary":   "#0ea5e9",
    "secondary": "#6366f1",
    "accent":    "#f59e0b",
    "dark":      "#0f172a",
    "surface":   "#1e293b",
    "muted":     "#334155",
}

_STATIC      = Path(__file__).parent / "static"
_LOGO_WHITE  = "/static/haystack_logo_white.png"
_header_logo = _LOGO_WHITE if (_STATIC / "haystack_logo.png").exists() else ""
_drawer_logo = _LOGO_WHITE if (_STATIC / "haystack_logo_white.png").exists() else ""
_icon_logo = _LOGO_WHITE if (_STATIC / "haystack_icon_logo.png").exists() else ""


@contextmanager
def frame(title: str):
    ui.colors(
        primary   = COLORS["primary"],
        secondary = COLORS["secondary"],
        accent    = COLORS["accent"],
        dark      = COLORS["dark"],
    )

    with ui.header(elevated=True).classes(
        "bg-[#0f172a] text-white items-center justify-between px-4 py-2"
    ):
        with ui.row().classes("items-center gap-3"):
            with ui.link(target=HAYSTACK_URL):
                ui.image(_icon_logo).classes("text-sky-400 text-3xl").tooltip("MIT Haystack Observatory")
            with ui.column().classes("gap-0 leading-tight"):
                ui.label("ASTRA").classes(
                    "text-xl font-bold tracking-widest text-sky-300"
                )
                ui.label("Automated Small Telescope for Radio Astronomy").classes(
                    "text-xs text-slate-400 tracking-wide"
                )
        with ui.row().classes("items-center gap-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("circle").classes("text-emerald-400 text-sm")
                ui.label("System Online").classes("text-sm text-slate-300")
            ui.element("div").classes("w-px h-6 bg-slate-700")
            if _header_logo:
                ui.image(_header_logo).classes(
                    "h-7 w-auto object-contain opacity-90 "
                    "hover:opacity-100 transition-opacity"
                ).tooltip("MIT Haystack Observatory")
            else:
                with ui.column().classes("gap-0 leading-none items-end"):
                    ui.label("MIT").classes(
                        "text-[10px] font-bold tracking-widest "
                        "text-slate-300 leading-tight"
                    )
                    ui.label("Haystack Observatory").classes(
                        "text-[9px] text-slate-500 leading-tight"
                    )

    with ui.left_drawer(fixed=True).classes(
        "bg-[#1e293b] pt-4 flex flex-col justify-between"
    ):
        with ui.column().classes("w-full"):
            _nav_links()
        with ui.column().classes(
            "w-full border-t border-slate-700/60 mt-4 pt-4 pb-4 px-4 gap-1"
        ):
            if _drawer_logo:
                ui.image(_drawer_logo).classes(
                    "w-full max-w-[160px] h-auto object-contain "
                    "opacity-70 hover:opacity-95 transition-opacity mx-auto"
                ).tooltip("MIT Haystack Observatory")
            else:
                ui.label("MIT Haystack Observatory").classes(
                    "text-[10px] text-slate-500 tracking-wide text-center"
                )
            ui.label("MIT Haystack Observatory").classes(
                "text-[9px] text-slate-600 text-center tracking-wide leading-tight"
            )
            ui.label("ASTRA Development - F. Lind and J. Lind (2026)").classes(
                            "text-[9px] text-slate-600 text-center tracking-wide leading-tight"
                        )

    with ui.column().classes("w-full p-6 gap-6 bg-[#0f172a] min-h-screen"):
        ui.label(title).classes("text-2xl font-semibold text-white")
        yield


def _section_label(text: str) -> None:
    ui.label(text).classes(
        "text-xs font-bold text-slate-500 tracking-widest px-4 mt-3 mb-1"
    )


def _separator() -> None:
    ui.separator().classes("bg-slate-700/60 mx-4 my-2")


def _internal_link(icon_name: str, label: str, path: str) -> None:
    with ui.link(target=path).classes("no-underline w-full"):
        with ui.row().classes(
            "items-center gap-3 px-4 py-3 rounded-lg cursor-pointer "
            "hover:bg-sky-900/40 text-slate-300 hover:text-sky-300 transition-colors"
        ):
            ui.icon(icon_name).classes("text-lg")
            ui.label(label).classes("text-sm font-medium")


def _external_link(
    icon_name:  str,
    label:      str,
    url:        str,
    sublabel:   str = "",
    icon_color: str = "text-slate-400",
) -> None:
    with ui.link(target=url, new_tab=True).classes("no-underline w-full"):
        with ui.row().classes(
            "items-center gap-3 px-4 py-3 rounded-lg cursor-pointer "
            "hover:bg-slate-700/50 text-slate-400 hover:text-slate-200 "
            "transition-colors group"
        ):
            ui.icon(icon_name).classes(f"text-lg {icon_color} shrink-0")
            with ui.column().classes("gap-0 flex-1 min-w-0"):
                ui.label(label).classes("text-sm font-medium leading-tight")
                if sublabel:
                    ui.label(sublabel).classes(
                        "text-[10px] text-slate-600 group-hover:text-slate-500 "
                        "leading-tight truncate"
                    )
            ui.icon("open_in_new").classes(
                "text-xs text-slate-600 group-hover:text-slate-400 "
                "shrink-0 transition-colors"
            )


def _nav_links() -> None:
    _section_label("NAVIGATION")
    _internal_link("nights_stay",    "Sky View",    "/")
    _internal_link("my_location",    "Control",     "/antenna")
    _internal_link("graphic_eq",     "Radio",       "/spectrometer")
    _internal_link("camera_alt",     "Camera",      "/camera")
    _internal_link("settings",       "Settings",    "/settings")

    _separator()

    _section_label("TOOLS")
    
    _external_link(
        icon_name  = "science",
        label      = "Notebook",
        url        = MARIMO_URL,
        sublabel   = "localhost:2718  ·  interactive Python",
        icon_color = "text-violet-400",
    )

    _external_link(
            icon_name  = "nights_stay",
            label      = "Sky Tonight",
            url        = STELLARIUM_URL,
            sublabel   = "Online sky information",
            icon_color = "text-violet-400",
    )

    _external_link(
                icon_name  = "camera_alt",
                label      = "Astrometry",
                url        = ASTROMETRY_URL,
                sublabel   = "Online stellar image lookup ",
                icon_color = "text-violet-400",
    )
    

    _separator()

    _section_label("RESOURCES")

    _external_link(
        icon_name  = "school",
        label      = "Lessons",
        url        = LESSONS_URL,
        sublabel   = "github.io/astra/lessons",
        icon_color = "text-emerald-400",
    )
     
    _external_link(
        icon_name  = "menu_book",
        label      = "Documentation",
        url        = DOCS_URL,
        sublabel   = "github.io/astra/docs",
        icon_color = "text-sky-400",
    )
    _external_link(
        icon_name  = "help_outline",
        label      = "Help",
        url        = HELP_URL,
        sublabel   = "github.io/astra/help",
        icon_color = "text-amber-400",
    )

    _external_link(
        icon_name  = "help_outline",
        label      = "About",
        url        = ABOUT_URL,
        sublabel   = "github.io/astra/about",
        icon_color = "text-sky-400",
    )
 
    _external_link(
        icon_name  = "help_outline",
        label      = "License",
        url        = LICENSE_URL,
        sublabel   = "github.io/astra/license",
        icon_color = "text-sky-400",
    )
 