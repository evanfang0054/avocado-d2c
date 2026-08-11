"""SceneNode — typed view over Figma REST API node JSON.

Figma nodes are polymorphic. Rather than 16 separate dataclasses, we use
one SceneNode with optional fields grouped by purpose. The `type` field
discriminates which fields are populated.

Field availability notes (per design docs):
  - REST API returns `cornerRadius` as scalar OR null (not 4-tuple;
    individual corners come from `topLeftRadius` etc. only on some nodes).
  - `boundVariables` is present but value references require extra resolve.
  - `sharedPluginData` is NOT in REST API (Plugin SDK only). This is the
    root cause pre-marked components can't be auto-recognized.
  - `absoluteBoundingBox` is {x,y,width,height} in absolute file coords.
  - TEXT.style is a separate dict (see TextStyle).
  - `children` only present on container types (FRAME/GROUP/INSTANCE/etc).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NodeType = Literal[
    "FRAME",
    "GROUP",
    "COMPONENT",
    "INSTANCE",
    "TEXT",
    "RECTANGLE",
    "LINE",
    "ELLIPSE",
    "VECTOR",
    "STAR",
    "POLYGON",
    "BOOLEAN_OPERATION",
    "SLICE",
    "STICKY",
    "SECTION",
    "CONNECTOR",
    "SLOT",
]


@dataclass
class Box:
    """Bounding box in absolute file coordinates."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_dict(cls, d: dict | None) -> Box | None:
        if not d:
            return None
        return cls(
            x=float(d["x"]),
            y=float(d["y"]),
            width=float(d["width"]),
            height=float(d["height"]),
        )


@dataclass
class Color:
    """RGBA color (0..1 range)."""

    r: float
    g: float
    b: float
    a: float = 1.0

    @classmethod
    def from_dict(cls, d: dict | None) -> Color | None:
        if not d:
            return None
        return cls(
            r=float(d.get("r", 0)),
            g=float(d.get("g", 0)),
            b=float(d.get("b", 0)),
            a=float(d.get("a", 1.0)),
        )

    def to_rgba_str(self) -> str:
        if self.a >= 1.0:
            r, g, b = (round(c * 255) for c in (self.r, self.g, self.b))
            return f"#{r:02x}{g:02x}{b:02x}"
        r, g, b = (round(c * 255) for c in (self.r, self.g, self.b))
        return f"rgba({r}, {g}, {b}, {round(self.a, 2)})"


@dataclass
class Paint:
    """One fill/stroke entry. type ∈ {SOLID, GRADIENT_*, IMAGE, etc.}"""

    type: str  # SOLID / GRADIENT_LINEAR / GRADIENT_RADIAL / IMAGE / ...
    visible: bool = True
    opacity: float = 1.0
    color: Color | None = None
    # Gradient-only
    gradient_handle_positions: list[dict] = field(default_factory=list)
    gradient_stops: list[dict] = field(default_factory=list)
    # Image-only
    image_ref: str | None = None  # Figma image ref; needs separate resolve
    scale_mode: str | None = None  # FILL / FIT / CROP / TILE_L...
    image_transform: list[list[float]] | None = None
    rotation: float | None = None
    # Figma image filters: {contrast: -1..1, saturation: -1..1, exposure: -1..1}
    # 0 = no change; contrast/saturation 0 in Figma means normal (no shift).
    filters: dict | None = None
    # Paint-embedded boundVariables: {color: {type, id}, ...}
    bound_variables: dict | None = None
    # Paint-level blendMode: per-fill blend; None means inherit node blend.
    blend_mode: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Paint:
        return cls(
            type=d.get("type", "SOLID"),
            visible=d.get("visible", True),
            opacity=float(d.get("opacity", 1.0)),
            color=Color.from_dict(d.get("color")),
            gradient_handle_positions=d.get("gradientHandlePositions", []) or [],
            gradient_stops=d.get("gradientStops", []) or [],
            image_ref=d.get("imageRef"),
            scale_mode=d.get("scaleMode"),
            image_transform=d.get("imageTransform"),
            rotation=d.get("rotation"),
            filters=d.get("filters"),
            bound_variables=d.get("boundVariables"),
            blend_mode=d.get("blendMode"),
        )


@dataclass
class Effect:
    """Visual effect: DROP_SHADOW / INNER_SHADOW / LAYER_BLUR / BACKGROUND_BLUR."""

    type: str
    visible: bool = True
    radius: float = 0.0
    color: Color | None = None
    blend_mode: str | None = None
    offset: dict | None = None  # {x, y}
    spread: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> Effect:
        return cls(
            type=d.get("type", "DROP_SHADOW"),
            visible=d.get("visible", True),
            radius=float(d.get("radius", 0)),
            color=Color.from_dict(d.get("color")),
            blend_mode=d.get("blendMode"),
            offset=d.get("offset"),
            spread=float(d.get("spread", 0)),
        )


@dataclass
class TextStyle:
    """TEXT node.style sub-dict."""

    font_family: str | None = None
    font_post_script_name: str | None = None
    font_size: float | None = None
    font_weight: float | None = None
    font_style: str | None = None  # "Italic" / "Normal"
    text_align_horizontal: str | None = None  # LEFT/CENTER/RIGHT/JUSTIFIED
    text_align_vertical: str | None = None  # TOP/CENTER/BOTTOM
    text_case: str | None = None  # ORIGINAL/UPPER/LOWER/TITLE
    text_decoration: str | None = None  # NONE/UNDERLINE/STRIKETHROUGH
    letter_spacing: float | None = None
    line_height_px: float | None = None
    line_height_percent: float | None = None
    line_height_unit: str | None = None  # PIXELS/PERCENT/AUTO/INSIDE
    paragraph_spacing: float | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> TextStyle | None:
        if not d:
            return None
        return cls(
            font_family=d.get("fontFamily"),
            font_post_script_name=d.get("fontPostScriptName"),
            font_size=d.get("fontSize"),
            font_weight=d.get("fontWeight"),
            font_style=d.get("fontStyle"),
            text_align_horizontal=d.get("textAlignHorizontal"),
            text_align_vertical=d.get("textAlignVertical"),
            text_case=d.get("textCase"),
            text_decoration=d.get("textDecoration"),
            letter_spacing=(float(d["letterSpacing"]) if "letterSpacing" in d else None),
            line_height_px=d.get("lineHeightPx"),
            line_height_percent=d.get("lineHeightPercent"),
            line_height_unit=d.get("lineHeightUnit"),
            paragraph_spacing=(float(d["paragraphSpacing"]) if "paragraphSpacing" in d else None),
        )


@dataclass
class SceneNode:
    """A single Figma node.

    Optional fields are None when not present in source JSON. Use `type`
    to decide which fields are meaningful for a given node.
    """

    # ── identification ──
    id: str
    name: str
    type: NodeType

    # ── geometry ──
    box: Box | None = None  # absoluteBoundingBox
    render_bounds: Box | None = None  # absoluteRenderBounds
    rotation: float = 0.0  # rotation in degrees (VECTOR etc.)
    # relativeTransform is a 2×3 affine matrix [[a,b,tx],[c,d,ty]] in the
    # parent's coordinate space. More authoritative than `rotation` for
    # deriving the visual angle of a node.
    relative_transform: list[list[float]] | None = None

    # ── hierarchy ──
    children: list[SceneNode] = field(default_factory=list)
    visible: bool = True
    locked: bool = False
    clips_content: bool | None = None  # FRAME/GROUP/etc
    # overflowDirection: NONE / HORIZONTAL_SCROLLING / VERTICAL_SCROLLING /
    # HORIZONTAL_AND_VERTICAL_SCROLLING. When non-NONE, Figma clips children
    # to the frame bbox along the scrolling axis(es) and lets users scroll.
    overflow_direction: str | None = None

    # ── auto layout (FRAME/INSTANCE/COMPONENT) ──
    layout_mode: str | None = None  # NONE/HORIZONTAL/VERTICAL
    layout_wrap: str | None = None  # NO_WRAP/WRAP (Figma Auto Layout wrap)
    primary_axis_sizing_mode: str | None = None  # FIXED/AUTO/MAX
    counter_axis_sizing_mode: str | None = None
    primary_axis_align_items: str | None = None
    counter_axis_align_items: str | None = None
    item_spacing: float = 0.0
    padding_top: float = 0.0
    padding_right: float = 0.0
    padding_bottom: float = 0.0
    padding_left: float = 0.0
    layout_align: str | None = None  # INHERIT/STRETCH
    layout_grow: float = 0.0
    layout_positioning: str | None = None  # AUTO/ABSOLUTE
    layout_sizing_horizontal: str | None = None  # FIXED/HUG/FILL
    layout_sizing_vertical: str | None = None
    min_width: float | None = None

    # ── visual style ──
    fills: list[Paint] = field(default_factory=list)
    strokes: list[Paint] = field(default_factory=list)
    stroke_weight: float | None = None
    stroke_align: str | None = None  # INSIDE/OUTSIDE/CENTER
    individual_stroke_weights: dict | None = None  # {top, right, bottom, left}
    corner_radius: float | None = None
    corner_smoothing: float | None = None
    # Dashed strokes: non-empty list → `border-style: dashed`.
    dash_pattern: list[float] = field(default_factory=list)
    blend_mode: str | None = None  # PASS_THROUGH/NORMAL/MULTIPLY/...
    effects: list[Effect] = field(default_factory=list)
    opacity: float = 1.0

    # ── TEXT-only ──
    characters: str | None = None
    text_style: TextStyle | None = None
    style_override_table: dict[str, Any] = field(default_factory=dict)
    character_style_overrides: list[int] = field(default_factory=list)

    # ── INSTANCE/COMPONENT-only ──
    component_id: str | None = None
    component_properties: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)

    # ── VECTOR-only (partial) ──
    boolean_operation: str | None = None

    # ── raw payload (debug, optional) ──
    raw: dict | None = None

    @classmethod
    def from_dict(cls, d: dict) -> SceneNode:
        children = [cls.from_dict(c) for c in d.get("children", []) or []]
        return cls(
            id=str(d["id"]),
            name=d.get("name", ""),
            type=d.get("type", "FRAME"),
            box=Box.from_dict(d.get("absoluteBoundingBox")),
            render_bounds=Box.from_dict(d.get("absoluteRenderBounds")),
            rotation=float(d.get("rotation", 0.0) or 0.0),
            relative_transform=d.get("relativeTransform"),
            children=children,
            visible=d.get("visible", True),
            locked=d.get("locked", False),
            clips_content=d.get("clipsContent"),
            overflow_direction=d.get("overflowDirection"),
            layout_mode=d.get("layoutMode"),
            layout_wrap=d.get("layoutWrap"),
            primary_axis_sizing_mode=d.get("primaryAxisSizingMode"),
            counter_axis_sizing_mode=d.get("counterAxisSizingMode"),
            primary_axis_align_items=d.get("primaryAxisAlignItems"),
            counter_axis_align_items=d.get("counterAxisAlignItems"),
            item_spacing=float(d.get("itemSpacing", 0.0) or 0.0),
            padding_top=float(d.get("paddingTop", 0.0) or 0.0),
            padding_right=float(d.get("paddingRight", 0.0) or 0.0),
            padding_bottom=float(d.get("paddingBottom", 0.0) or 0.0),
            padding_left=float(d.get("paddingLeft", 0.0) or 0.0),
            layout_align=d.get("layoutAlign"),
            layout_grow=float(d.get("layoutGrow", 0.0) or 0.0),
            layout_positioning=d.get("layoutPositioning"),
            layout_sizing_horizontal=d.get("layoutSizingHorizontal"),
            layout_sizing_vertical=d.get("layoutSizingVertical"),
            min_width=(float(d["minWidth"]) if d.get("minWidth") is not None else None),
            fills=[Paint.from_dict(p) for p in d.get("fills", []) or []],
            strokes=[Paint.from_dict(p) for p in d.get("strokes", []) or []],
            stroke_weight=(
                float(d["strokeWeight"])
                if "strokeWeight" in d and d["strokeWeight"] is not None
                else None
            ),
            stroke_align=d.get("strokeAlign"),
            individual_stroke_weights=d.get("individualStrokeWeights"),
            corner_radius=(
                float(d["cornerRadius"])
                if "cornerRadius" in d and d["cornerRadius"] is not None
                else None
            ),
            corner_smoothing=d.get("cornerSmoothing"),
            dash_pattern=list(d.get("dashPattern", []) or []),
            blend_mode=d.get("blendMode"),
            effects=[Effect.from_dict(e) for e in d.get("effects", []) or []],
            opacity=float(d.get("opacity", 1.0) or 1.0),
            characters=d.get("characters"),
            text_style=TextStyle.from_dict(d.get("style")),
            style_override_table=dict(d.get("styleOverrideTable", {}) or {}),
            character_style_overrides=list(d.get("characterStyleOverrides", []) or []),
            component_id=d.get("componentId"),
            component_properties=dict(d.get("componentProperties", {}) or {}),
            overrides=dict(d.get("overrides", {}) or {}),
            boolean_operation=d.get("booleanOperation"),
            raw=d,  # optional debug aid; strip in production if memory matters
        )
