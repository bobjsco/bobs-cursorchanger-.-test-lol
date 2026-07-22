"""
shapes.py
=========
QPainterPath definitions for all cursor shapes.

Each path is centered at (0, 0) and sized to fit inside a circle of the
given radius. EXCEPTION: 'Arrow' has its tip at (0, 0) so it points
correctly when the overlay window is centered on the cursor.

Shapes supported:
  Circle, Ring, Square, Diamond, Triangle, Star, Heart,
  Hexagon, Crosshair, Arrow, Dot, Pentagon, Crescent, Lightning
"""
from __future__ import annotations

import math
from typing import List

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath, QPolygonF


SHAPE_NAMES: List[str] = [
    "Circle", "Ring", "Square", "Diamond", "Triangle",
    "Star", "Heart", "Hexagon", "Crosshair", "Arrow",
    "Dot", "Pentagon", "Crescent", "Lightning",
]


def shape_path(name: str, radius: float) -> QPainterPath:
    """Return a QPainterPath for the given shape, sized to fit inside a
    circle of `radius` centered at origin.

    For 'Arrow', the tip is at origin (so it acts as a classic cursor).
    """
    r = max(1.0, float(radius))

    if name == "Circle":
        p = QPainterPath()
        p.addEllipse(QRectF(-r, -r, r * 2, r * 2))
        return p

    if name == "Ring":
        # Outer circle; inner is subtracted
        p = QPainterPath()
        p.addEllipse(QRectF(-r, -r, r * 2, r * 2))
        inner = r * 0.65
        sub = QPainterPath()
        sub.addEllipse(QRectF(-inner, -inner, inner * 2, inner * 2))
        return p.subtracted(sub)

    if name == "Square":
        p = QPainterPath()
        # Slightly rounded corners look better
        p.addRoundedRect(QRectF(-r, -r, r * 2, r * 2), r * 0.15, r * 0.15)
        return p

    if name == "Diamond":
        p = QPainterPath()
        poly = QPolygonF([QPointF(0, -r), QPointF(r, 0),
                          QPointF(0, r), QPointF(-r, 0)])
        p.addPolygon(poly)
        p.closeSubpath()
        return p

    if name == "Triangle":
        # Equilateral, pointing up
        p = QPainterPath()
        h = r * math.sqrt(3) / 2
        poly = QPolygonF([
            QPointF(0, -r),
            QPointF(h, r * 0.6),
            QPointF(-h, r * 0.6),
        ])
        p.addPolygon(poly)
        p.closeSubpath()
        return p

    if name == "Star":
        # 5-pointed star
        p = QPainterPath()
        points = []
        for i in range(10):
            angle = math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.42
            points.append(QPointF(rr * math.cos(angle),
                                   -rr * math.sin(angle)))
        p.addPolygon(QPolygonF(points))
        p.closeSubpath()
        return p

    if name == "Heart":
        # Smooth heart with cubic Beziers
        p = QPainterPath()
        p.moveTo(0, r * 0.95)
        p.cubicTo(r * 1.4, r * 0.2, r * 0.95, -r * 1.05, 0, -r * 0.35)
        p.cubicTo(-r * 0.95, -r * 1.05, -r * 1.4, r * 0.2, 0, r * 0.95)
        p.closeSubpath()
        return p

    if name == "Hexagon":
        p = QPainterPath()
        points = []
        for i in range(6):
            angle = math.pi / 6 + i * math.pi / 3
            points.append(QPointF(r * math.cos(angle),
                                   r * math.sin(angle)))
        p.addPolygon(QPolygonF(points))
        p.closeSubpath()
        return p

    if name == "Crosshair":
        # Plus sign
        thick = r * 0.32
        p = QPainterPath()
        p.addRoundedRect(QRectF(-thick, -r, thick * 2, r * 2),
                         thick * 0.3, thick * 0.3)
        p.addRoundedRect(QRectF(-r, -thick, r * 2, thick * 2),
                         thick * 0.3, thick * 0.3)
        return p

    if name == "Arrow":
        # Classic cursor arrow, tip at (0, 0), pointing down-right
        # Base outline (scaled)
        base = [
            (0, 0), (0, 16), (4, 12), (7, 18),
            (9, 17), (6, 11), (11, 11),
        ]
        scale = r / 11.0
        poly = QPolygonF([QPointF(x * scale, y * scale) for x, y in base])
        p = QPainterPath()
        p.addPolygon(poly)
        p.closeSubpath()
        return p

    if name == "Dot":
        p = QPainterPath()
        p.addEllipse(QRectF(-r * 0.4, -r * 0.4, r * 0.8, r * 0.8))
        return p

    if name == "Pentagon":
        p = QPainterPath()
        points = []
        for i in range(5):
            angle = math.pi / 2 + i * 2 * math.pi / 5
            points.append(QPointF(r * math.cos(angle),
                                   -r * math.sin(angle)))
        p.addPolygon(QPolygonF(points))
        p.closeSubpath()
        return p

    if name == "Crescent":
        # Two arcs: outer circle and offset inner circle (subtracted)
        p = QPainterPath()
        p.addEllipse(QRectF(-r, -r, r * 2, r * 2))
        sub = QPainterPath()
        sub.addEllipse(QRectF(-r * 0.4, -r * 1.0, r * 1.7, r * 1.7))
        return p.subtracted(sub)

    if name == "Lightning":
        # Stylized lightning bolt
        base = [
            (-0.2, -1.0), (0.5, -0.2), (0.1, -0.1),
            (0.4, 1.0), (-0.4, 0.15), (0.0, 0.05),
            (-0.5, -0.6),
        ]
        scale = r
        poly = QPolygonF([QPointF(x * scale, y * scale) for x, y in base])
        p = QPainterPath()
        p.addPolygon(poly)
        p.closeSubpath()
        return p

    # Fallback: circle
    p = QPainterPath()
    p.addEllipse(QRectF(-r, -r, r * 2, r * 2))
    return p


def shape_hotspot(name: str, radius: float) -> QPointF:
    """Where clicks should land, relative to the shape's origin (0,0).

    For Arrow, the tip is already at (0,0), so hotspot is (0,0).
    For everything else, the center is the hotspot.
    """
    if name == "Arrow":
        return QPointF(0, 0)
    return QPointF(0, 0)
