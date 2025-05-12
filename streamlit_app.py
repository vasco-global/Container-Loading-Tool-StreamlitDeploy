import base64
from datetime import date

import streamlit as st
import pandas as pd
import math
import re
import colorsys, json
import streamlit.components.v1 as components
import io

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image as RLImage,
    PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Rect

st.set_page_config(layout="wide")

if 'belt_id_counter' not in st.session_state:
    st.session_state['belt_id_counter'] = 0
if 'needs_reordering' not in st.session_state:
    st.session_state["needs_reordering"] = True
if 'belts' not in st.session_state:
    st.session_state.belts = []
if "heavy_dialog_seen" not in st.session_state:
    st.session_state["heavy_dialog_seen"] = set()

if "topview_refresh_counter" not in st.session_state:
    st.session_state["topview_refresh_counter"] = 0

# ------------------- Lookup-Tabellen & Container-Daten -------------------
carcassThicknessLookup = {
    "EP100": 1.0, "EP125": 1.0, "EP150": 1.1, "EP200": 1.2, "EP250": 1.4,
    "EP300": 1.6, "EP350": 1.7, "EP400": 1.9, "EP500": 2.2, "EP600": 2.5
}
carcassThicknessLookupRow2 = {
    "EP100": 1.7, "EP125": 1.7, "EP150": 1.7, "EP200": 1.7, "EP250": 2.0,
    "EP300": 2.0, "EP350": 2.3, "EP400": 2.3, "EP500": 2.6, "EP600": 2.6
}
beltFabricLookup = {
    "EP100/1": "EP100", "EP125/1": "EP125", "EP160/2": "EP80", "EP200/1": "EP200",
    "EP200/2": "EP100", "EP250/2": "EP125", "EP315/1": "EP300", "EP315/2": "EP150",
    "EP315/3": "EP100", "EP400/2": "EP200", "EP400/3": "EP125", "EP500/2": "EP250",
    "EP500/3": "EP150", "EP500/4": "EP100", "EP500/5": "EP80", "EP630/3": "EP200",
    "EP630/4": "EP150", "EP630/5": "EP125", "EP800/3": "EP250", "EP800/4": "EP200",
    "EP800/5": "EP150", "EP800/6": "EP125", "EP1000/3": "EP300", "EP1000/4": "EP250",
    "EP1000/5": "EP200", "EP1000/6": "EP150", "EP1250/3": "EP400", "EP1250/4": "EP300",
    "EP1250/5": "EP250", "EP1250/6": "EP200", "EP1500/3": "EP500", "EP1500/4": "EP350",
    "EP1500/5": "EP300", "EP1600/3": "EP500", "EP1600/4": "EP400", "EP1600/5": "EP300",
    "EP1600/6": "EP250", "EP1600/8": "EP200", "EP2000/4": "EP500", "EP2000/5": "EP400",
    "EP2000/6": "EP300", "EP2500/4": "EP600", "EP2500/5": "EP500", "EP2500/6": "EP400",
    "EP450/3": "EP125",
    "XE250/2": "EP125", "XE315/2": "EP150", "XE400/2": "EP200", "XE400/3": "EP125",
    "XE500/3": "EP150", "XE500/4": "EP125", "XE630/3": "EP200", "XE630/4": "EP150",
    "XE800/4": "EP200", "XE1000/5": "EP200", "XE1000/6": "EP150", "XE1600/4": "EP400",
    "XE1600/5": "EP300"
}
steelCordLookup = {
    "ST630": 2.10, "ST800": 2.20, "ST1000": 2.20, "ST1250": 2.28,
    "ST1600": 2.40, "ST2000": 2.45, "ST2500": 2.60, "ST3150": 2.66,
    "ST3500": 2.79, "ST4000": 2.90, "ST4500": 2.96, "ST5000": 3.05,
    "ST5400": 3.08
}
containerData = {
    "20ft": {"height": 2.392, "width": 2.352, "length": 5.76, "max_load": 28180, "maxVolume": 33.136},
    "40ft": {"height": 2.392, "width": 2.352, "length": 12.029, "max_load": 27600, "maxVolume": 67.617},
    "40ft High Cube": {"height": 2.6924, "width": 2.352, "length": 12.029, "max_load": 27600, "maxVolume": 67.617}
}

# ------------------- Hilfsfunktionen -------------------
_last_hue = 0.0


def get_random_color():
    global _last_hue
    _last_hue = (_last_hue + 0.618033988749895) % 1
    s = 0.9
    v = 0.9
    r, g, b = colorsys.hsv_to_rgb(_last_hue, s, v)
    return '#{:02X}{:02X}{:02X}'.format(int(r * 255), int(g * 255), int(b * 255))


def format_number(value):
    try:
        val = float(value)
        return str(int(val)) if val.is_integer() else f"{val:.2f}"
    except:
        return str(value)


# ------------------- Parsing-Funktion (erweitert) -------------------
def parse_belt(spec, length_str, core_diameter, oval_segment_length,
               steel_cord_diameter, rip_stop_layers, is_oval):
    belt_center = center_chevrons
    flat = False
    if spec.strip() == "" or length_str.strip() == "":
        st.error("Please insert belt-specification and length (in m)")
        return None
    try:
        length = float(length_str)
    except ValueError:
        st.error("invalid length")
        return None
    if core_diameter is None or core_diameter <= 0:
        core_diameter = 0.30

    pattern = (
        r"^(\d+)\s+"  # Gruppe 1: Breite
        r"([A-Z]+)?"  # Gruppe 2: Fabric-Typ
        r"(\d+)?"  # Gruppe 3: Carcass-Nummer
        r"(?:\/(\d+(?:\+\d+)*))?"  # Gruppe 4: Layer-Info, z.B. "3" oder "3+4"
        r"(?:-([\d.]+R?:[\d.]+))?"  # Gruppe 5: Cover-Layer, z.B. "4:2"
        r"(?:-([^\/\s]+))?"  # Gruppe 6: Gurtqualität (String, außer Slash oder Leerzeichen)
        r"(?:\s*\/\s*([^\/\s]+))?"  # Gruppe 7: Edge Type (beliebiger String)
        r"(?:\s*\/\s*([^\/\s]+)-(\d+)-P(\d+))?"  # Gruppen 8-10: Chevron-Profil, Cleat-Höhe, Profilbreite
        r"$"
    )
    m = re.match(pattern, spec)
    if not m:
        st.error("Format error. Please check your input.")
        return None

    width_str = m.group(1) or "n/a"
    fabricType = m.group(2) or "n/a"
    carcass_num = m.group(3) or "n/a"
    layerInfo = m.group(4) or "n/a"
    coverLayer = m.group(5) or "n/a"
    quality = m.group(6) or "n/a"
    edgeType = m.group(7) or ""
    chevronProfile = m.group(8) or ""
    chevronCleatHeight = float(m.group(9)) if m.group(9) else 0.0
    chevronProfileWidth = m.group(10) or ""
    width = float(width_str)
    is_oval = oval_segment_length > 0

    try:
        parts = coverLayer.split(":")
        cs_str = parts[0].rstrip("R") if parts and parts[0] else ""
        carryingSide = float(cs_str) if cs_str else 0.0
        rs_str = parts[1] if len(parts) > 1 else ""
        runningSide = float(rs_str) if rs_str else 0.0
    except Exception:
        carryingSide = 0
        runningSide = 0

    if fabricType.startswith("ST"):
        belt_type = "steelcord"
    elif "R" in coverLayer:
        belt_type = "ripstop"
    elif chevronProfile != "":
        belt_type = "chevron"
    else:
        belt_type = "standard"

    if belt_type in ["standard", "ripstop", "chevron"]:
        try:
            layers = [int(x) for x in layerInfo.split("+") if x != ""]
        except Exception:
            layers = [0]
        epLayers = layers[0] if len(layers) >= 1 else 0
        xeLayers = layers[1] if len(layers) >= 2 else 0
    else:
        epLayers, xeLayers = "/", "/"

    # 5. Lookup-Parameter
    carcassStrength = f"{fabricType}{carcass_num}" if carcass_num != "error" else f"{fabricType}000"
    if belt_type == "steelcord":
        fabricUsed = beltFabricLookup.get(carcassStrength, 1.0)
        steelCordWeightParameter = steelCordLookup.get(carcassStrength, 1.0)

    else:
        key = f"{fabricType}{carcassStrength[len(fabricType):]}/{epLayers}"
        fabricUsed = beltFabricLookup.get(key, carcassStrength)
        carcassThicknessPerPly = carcassThicknessLookup.get(fabricUsed, 0.0)
        carcassThicknessPerPlyRow2 = carcassThicknessLookupRow2.get(fabricUsed, 0.0)

    # Fall 1: steelcord & round
    if belt_type == "steelcord" and (is_oval is False):
        Belt_Thickness = steel_cord_diameter + carryingSide + runningSide
        Roll_Diameter = math.sqrt(Belt_Thickness * (length / 1000) * 1.27 + core_diameter)
        Weight_Per_Meter = ((Belt_Thickness / 1.5) * (width / 1000)) * steelCordWeightParameter
        Weight_Per_Roll = ((Belt_Thickness / 1.5) * (width / 1000) * length) * steelCordWeightParameter
        Base_Dims = (width / 1000, Roll_Diameter)
        Height_3D = Roll_Diameter

    # Fall 2: steelcord & oval
    elif belt_type == "steelcord" and (is_oval is True):
        Belt_Thickness = steel_cord_diameter + carryingSide + runningSide
        Weight_Per_Meter = ((Belt_Thickness / 1.5) * (width / 1000)) * steelCordWeightParameter
        Weight_Per_Roll = Weight_Per_Meter * length
        Oval_Height = (math.sqrt(oval_segment_length ** 2 + 4 * (math.pi / 4) * (
                (core_diameter ** 2 / 4) * math.pi + (oval_segment_length * core_diameter) + (
                (Belt_Thickness * length) / 1000))) - oval_segment_length) / (math.pi / 2)
        Oval_Roll_Length = oval_segment_length + Oval_Height
        Base_Dims = (width / 1000, Oval_Roll_Length)
        Height_3D = Oval_Height

    # Fall 3: standard & round
    elif belt_type == "standard" and (is_oval is False):
        Belt_Thickness = (carcassThicknessPerPly * epLayers) + (1.75 * xeLayers) + carryingSide + runningSide
        Roll_Diameter = math.sqrt(Belt_Thickness * (length / 1000) * 1.27 + core_diameter)
        Weight_Per_Meter = (((((carcassThicknessPerPly * epLayers) + carryingSide + runningSide) - (
                epLayers * carcassThicknessPerPly)) / 1.5 + epLayers) * (
                                    width / 1000) * length * carcassThicknessPerPlyRow2 + (
                                    width / 1000) * 2.1 * length * xeLayers + (
                                    width / 1000) * 2.6 * length * 0) / length
        Weight_Per_Roll = Weight_Per_Meter * length
        Base_Dims = (width / 1000, Roll_Diameter)
        Height_3D = Roll_Diameter

    # Fall 4: standard & oval
    elif belt_type == "standard" and (is_oval is True):
        Belt_Thickness = (carcassThicknessPerPly * epLayers) + (1.75 * xeLayers) + carryingSide + runningSide
        Weight_Per_Meter = (((((carcassThicknessPerPly * epLayers) + carryingSide + runningSide) - (
                epLayers * carcassThicknessPerPly)) / 1.5 + epLayers) * (
                                    width / 1000) * length * carcassThicknessPerPlyRow2 + (
                                    width / 1000) * 2.1 * length * xeLayers + (
                                    width / 1000) * 2.6 * length * 0) / length
        Weight_Per_Roll = Weight_Per_Meter * length
        Oval_Height = (math.sqrt(oval_segment_length ** 2 + 4 * (math.pi / 4) * (
                (core_diameter ** 2 / 4) * math.pi + (oval_segment_length * core_diameter) + (
                (Belt_Thickness * length) / 1000))) - oval_segment_length) / (math.pi / 2)
        Oval_Roll_Length = oval_segment_length + Oval_Height
        Base_Dims = (width / 1000, Oval_Roll_Length)
        Height_3D = Oval_Height

    # Fall 5: ripstop & round
    elif belt_type == "ripstop" and (is_oval is False):
        Belt_Thickness = (carcassThicknessPerPly * epLayers) + (1.75 * xeLayers) + carryingSide + runningSide
        Roll_Diameter = math.sqrt(Belt_Thickness * (length / 1000) * 1.27 + core_diameter)
        Ripstop_Layers = int(rip_stop_layers)
        Weight_Per_Meter = (((((carcassThicknessPerPly * epLayers) + carryingSide + runningSide) - (
                epLayers * carcassThicknessPerPly)) / 1.5 + epLayers) * (
                                    width / 1000) * length * carcassThicknessPerPlyRow2 + (
                                    width / 1000) * 2.1 * length * xeLayers + (
                                    width / 1000) * 2.6 * length * Ripstop_Layers) / length
        Weight_Per_Roll = Weight_Per_Meter * length
        Base_Dims = (width / 1000, Roll_Diameter)
        Height_3D = Roll_Diameter

    # Fall 6: ripstop & oval
    elif belt_type == "ripstop" and (is_oval is True):
        Belt_Thickness = (carcassThicknessPerPly * epLayers) + (1.75 * xeLayers) + carryingSide + runningSide
        Ripstop_Layers = int(rip_stop_layers)
        Weight_Per_Meter = (((((carcassThicknessPerPly * epLayers) + carryingSide + runningSide) - (
                epLayers * carcassThicknessPerPly)) / 1.5 + epLayers) * (
                                    width / 1000) * length * carcassThicknessPerPlyRow2 + (
                                    width / 1000) * 2.1 * length * xeLayers + (
                                    width / 1000) * 2.6 * length * Ripstop_Layers) / length
        Weight_Per_Roll = Weight_Per_Meter * length
        Oval_Height = (math.sqrt(oval_segment_length ** 2 + 4 * (math.pi / 4) * (
                (core_diameter ** 2 / 4) * math.pi + (oval_segment_length * core_diameter) + (
                (Belt_Thickness * length) / 1000))) - oval_segment_length) / (math.pi / 2)
        Oval_Roll_Length = oval_segment_length + Oval_Height
        Base_Dims = (width / 1000, Oval_Roll_Length)
        Height_3D = Oval_Height

    # Fall 7: Chevron
    elif belt_type == "chevron":
        Belt_Thickness = (
                carcassThicknessLookup.get(fabricUsed, 0.0) * epLayers
                + 1.75 * xeLayers
                + carryingSide + runningSide
                + chevronCleatHeight
        )
        Roll_Diameter = math.sqrt(Belt_Thickness * (length / 1000) * 1.27 + core_diameter)
        Weight_Per_Meter = (
                                   (
                                           (
                                                   (carcassThicknessLookup.get(fabricUsed, 0.0) * epLayers)
                                                   + carryingSide + runningSide
                                                   - epLayers * carcassThicknessLookup.get(fabricUsed, 0.0)
                                           ) / 1.5
                                           + epLayers
                                   )
                                   * (width / 1000) * length * carcassThicknessLookupRow2.get(fabricUsed, 0.0)
                                   + (width / 1000) * 2.1 * length * xeLayers
                           ) / length
        Weight_Per_Roll = Weight_Per_Meter * length

        if Roll_Diameter >= 1.4:  # Ø ≥ 1 400 mm → Gürtel seitlich legen & stapeln
            flat = True
            Base_Dims = (Roll_Diameter, Roll_Diameter)  # quadratischer Footprint
            Height_3D = width / 1000  # Stapelhöhe = Gurtbreite
        else:  # kleinere Chevrons bleiben stehend
            flat = False
            Base_Dims = (width / 1000, Roll_Diameter)
            Height_3D = Roll_Diameter

        belt_center = center_chevrons

    belt_width_m = width / 1000
    initialPos = [0, 0]

    belt = {
        "spec": spec,
        "length": length,
        "width_mm": width,
        "belt_width": width / 1000,
        "fabricType": fabricType,
        "carcassStrength": carcassStrength,
        "epLayers": epLayers if belt_type != "steelcord" else "/",
        "xeLayers": xeLayers if belt_type != "steelcord" else "/",
        "carryingSide": carryingSide,
        "runningSide": runningSide,
        "beltThickness": Belt_Thickness,
        "rollDiameter": Roll_Diameter if not is_oval else Oval_Height,
        "weightPerMeter": Weight_Per_Meter,
        "weightPerRoll": Weight_Per_Roll,
        "isOval": is_oval,
        "ovalHeight": Oval_Height if is_oval else "N/A",
        "ovalRollLength": Oval_Roll_Length if is_oval else "N/A",
        "base_dims": Base_Dims,
        "height_3d": Height_3D,
        "color": get_random_color(),
        "initialPos": initialPos,
        "oval_segment_length": oval_segment_length,
        "steel_cord_diameter": steel_cord_diameter,
        "steelCordWeightParameter": steelCordWeightParameter if belt_type == "steelcord" else None,
        "rip_stop_layers": rip_stop_layers,
        "core_diameter": core_diameter,
        "quality": quality,
        "edgeType": edgeType,
        "chevronProfile": chevronProfile,
        "chevronCleatHeight": chevronCleatHeight,
        "chevronProfileWidth": chevronProfileWidth,
        "belt_type": belt_type,
        "flat": flat,
        "chevron_center": belt_center
    }
    return belt


# ------------------- Recalc-Funktion für einen aktualisierten Belt -------------------
def recalc_belt(old_belt, new_spec, new_length, new_core_diameter):
    new_belt = parse_belt(
        new_spec,
        str(new_length),
        new_core_diameter,
        old_belt.get("oval_segment_length", 0.0),
        old_belt.get("steel_cord_diameter", 0.0),
        old_belt.get("rip_stop_layers", 0),
        old_belt.get("isOval", False)
    )
    if new_belt is not None:
        new_belt["color"] = old_belt.get("color", new_belt["color"])
        new_belt["initialPos"] = old_belt.get("initialPos", new_belt["initialPos"])
        new_belt["position"] = old_belt.get("position", new_belt.get("position"))
        new_belt["placed_dims"] = old_belt.get("placed_dims", new_belt["base_dims"])
        new_belt["rotation_angle"] = old_belt.get("rotation_angle", 0)
        new_belt["id"] = old_belt.get("id")
    return new_belt


# ------------------- Container-Packing mittels Max Rectangles -------------------
def init_container(container):
    return {
        "id": None,
        "free_rectangles": [{"x": 0, "y": 0, "width": container["width"], "height": container["length"]}],
        "boxes": [],
        "used_weight": 0.0
    }


def choose_placement(free_rectangles, item):
    for rect in free_rectangles:
        if item["width"] <= rect["width"] and item["height"] <= rect["height"]:
            return rect
    return None


def split_free_rect(free_rect, placed):
    new_rects = []
    if free_rect["width"] - placed["width"] > 0:
        new_rects.append({
            "x": free_rect["x"] + placed["width"],
            "y": free_rect["y"],
            "width": free_rect["width"] - placed["width"],
            "height": placed["height"]
        })
    if free_rect["height"] - placed["height"] > 0:
        new_rects.append({
            "x": free_rect["x"],
            "y": free_rect["y"] + placed["height"],
            "width": free_rect["width"],
            "height": free_rect["height"] - placed["height"]
        })
    return new_rects


def update_free_rectangles(free_rectangles, used_rect):
    new_free_rects = []
    for rect in free_rectangles:
        if rect == used_rect:
            new_free_rects.extend(split_free_rect(rect, used_rect["placed"]))
        else:
            new_free_rects.append(rect)
    return new_free_rects


belt_buffer = 0.005


def rects_intersect(rect1, rect2):
    return not (
            rect1["x"] + rect1["width"] <= rect2["x"] or
            rect2["x"] + rect2["width"] <= rect1["x"] or
            rect1["y"] + rect1["height"] <= rect2["y"] or
            rect2["y"] + rect2["height"] <= rect1["y"]
    )


def subtract_rect(free_rect, used_rect):
    new_rects = []
    ix = max(free_rect["x"], used_rect["x"])
    iy = max(free_rect["y"], used_rect["y"])
    i_right = min(free_rect["x"] + free_rect["width"], used_rect["x"] + used_rect["width"])
    i_bottom = min(free_rect["y"] + free_rect["height"], used_rect["y"] + used_rect["height"])

    if ix >= i_right or iy >= i_bottom:
        return [free_rect]

    if iy > free_rect["y"]:
        new_rects.append({
            "x": free_rect["x"],
            "y": free_rect["y"],
            "width": free_rect["width"],
            "height": iy - free_rect["y"]
        })

    if i_bottom < free_rect["y"] + free_rect["height"]:
        new_rects.append({
            "x": free_rect["x"],
            "y": i_bottom,
            "width": free_rect["width"],
            "height": free_rect["y"] + free_rect["height"] - i_bottom
        })

    if used_rect["x"] > free_rect["x"]:
        new_rects.append({
            "x": free_rect["x"],
            "y": iy,
            "width": used_rect["x"] - free_rect["x"],
            "height": i_bottom - iy
        })

    if used_rect["x"] + used_rect["width"] < free_rect["x"] + free_rect["width"]:
        new_rects.append({
            "x": used_rect["x"] + used_rect["width"],
            "y": iy,
            "width": free_rect["x"] + free_rect["width"] - (used_rect["x"] + used_rect["width"]),
            "height": i_bottom - iy
        })
    return new_rects


def pack_belts_into_containers(belts, container, allow_rotation, forklift_limit):
    containers = []
    rejected_belts = []
    if not center_chevrons:
        chevrons = [b for b in belts if b.get('belt_type') == 'chevron' and b.get('flat', False)]
        others = [b for b in belts if not (b.get('belt_type') == 'chevron' and b.get('flat', False))]
        chevrons.sort(key=lambda b: b['base_dims'][0] * b['base_dims'][1], reverse=True)

        stacks = []
        for ch in chevrons:
            for stck in stacks:
                if stck['total_height'] + ch['height_3d'] <= container['height']:
                    stck['belts'].append(ch)
                    stck['total_height'] += ch['height_3d']
                    if (ch['base_dims'][0] * ch['base_dims'][1]) > (stck['base_dims'][0] * stck['base_dims'][1]):
                        stck['base_dims'] = ch['base_dims']
                    break
            else:
                stacks.append({
                    'belts': [ch],
                    'total_height': ch['height_3d'],
                    'base_dims': ch['base_dims']
                })

        belt_stacks = []
        for stck in stacks:
            belt_stacks.append({
                'belt_type': 'chevron',
                'flat': True,
                'chevron_center': False,
                'base_dims': stck['base_dims'],
                'height_3d': stck['total_height'],
                'weightPerRoll': sum(b['weightPerRoll'] for b in stck['belts']),
                'belts': stck['belts'],
            })

        belts_for_packing = others + belt_stacks
    else:
        belts_for_packing = belts

    object_items = [b for b in belts_for_packing if b.get("itemType") == "object"]
    if object_items:
        non_objects = [b for b in belts_for_packing if b.get("itemType") != "object"]
        object_items.sort(key=lambda b: b["base_dims"][0] * b["base_dims"][1], reverse=True)

        stacks = []
        for obj in object_items:
            for stck in stacks:
                if stck["total_height"] + obj["height_3d"] <= container["height"]:
                    stck["belts"].append(obj)
                    stck["total_height"] += obj["height_3d"]
                    stck["total_weight"] += obj["weightPerRoll"]
                    w0, l0 = stck["base_dims"]
                    w1, l1 = obj["base_dims"]
                    stck["base_dims"] = (max(w0, w1), max(l0, l1))
                    break
            else:
                stacks.append({
                    "belts": [obj],
                    "total_height": obj["height_3d"],
                    "total_weight": obj["weightPerRoll"],
                    "base_dims": obj["base_dims"]
                })

        object_stacks = []
        for stck in stacks:
            object_stacks.append({
                "itemType": "object",
                "flat": False,
                "base_dims": stck["base_dims"],
                "height_3d": stck["total_height"],
                "weightPerRoll": stck["total_weight"],
                "belts": stck["belts"],
                "belt_width": stck["base_dims"][0],
                "width_mm": stck["base_dims"][0] * 1000,
                "length": stck["base_dims"][1]
            })

        belts_for_packing = non_objects + object_stacks
    # ————————————————————————————————————————————————

    flat_belts = sorted(
        [b for b in belts_for_packing if b.get("flat", False)],
        key=lambda b: b["base_dims"][0] * b["base_dims"][1],
        reverse=True
    )
    other_belts = sorted(
        [b for b in belts_for_packing if not b.get("flat", False)],
        key=lambda b: b["base_dims"][0] * b["base_dims"][1],
        reverse=True
    )
    ordered_belts = flat_belts + other_belts

    for box in ordered_belts:
        if box["height_3d"] > container["height"]:
            st.error(
                f"Belt too high for Container: {box['spec']} ({box['height_3d']:.2f} m > {container['height']:.2f} m)")
            rejected_belts.append(box)
            continue
        placed = False
        if box.get("flat", False):
            placed_in_container = False
            for cont in containers:
                if "flat_stack_height" not in cont:
                    cont["flat_stack_height"] = belt_buffer

                if (cont["used_weight"] + box["weightPerRoll"] <= container["max_load"]) and \
                        (cont["flat_stack_height"] + box["height_3d"] <= container["height"]):

                    if box.get("chevron_center", True):
                        x = (container["width"] - box["base_dims"][0]) / 2
                        y = (container["length"] - box["base_dims"][1]) / 2
                    else:
                        fr = cont["free_rectangles"][0]
                        x = fr["x"]
                        y = fr["y"]
                    z = cont["flat_stack_height"]
                    box["position"] = (x, y, z)
                    box["placed_dims"] = box["base_dims"]
                    box["rotation_angle"] = 0
                    box["initialPos"] = (x + box["base_dims"][0] / 2,
                                         y + box["base_dims"][1] / 2)
                    cont["boxes"].append(box)
                    used_rect = {
                        "x": x,
                        "y": y,
                        "width": box["base_dims"][0],
                        "height": box["base_dims"][1]
                    }
                    cont["free_rectangles"] = update_free_rectangles(cont["free_rectangles"], used_rect)

                    cont["used_weight"] += box["weightPerRoll"]
                    cont["flat_stack_height"] = z + box["height_3d"] + belt_buffer

                    placed = True
                    placed_in_container = True
                    break

            if not placed_in_container:
                new_cont = init_container(container)
                new_cont["id"] = len(containers) + 1
                new_cont["flat_stack_height"] = belt_buffer
                if box.get("chevron_center", True):
                    x = (container["width"] - box["base_dims"][0]) / 2
                    y = (container["length"] - box["base_dims"][1]) / 2
                else:
                    fr = new_cont["free_rectangles"][0]
                    x = fr["x"]
                    y = fr["y"]
                z = new_cont["flat_stack_height"]
                box["position"] = (x, y, z)
                box["placed_dims"] = box["base_dims"]
                box["rotation_angle"] = 0
                box["initialPos"] = (x + box["base_dims"][0] / 2,
                                     y + box["base_dims"][1] / 2)
                new_cont["boxes"].append(box)
                used_rect = {
                    "x": x,
                    "y": y,
                    "width": box["base_dims"][0],
                    "height": box["base_dims"][1]
                }
                new_cont["free_rectangles"] = update_free_rectangles(new_cont["free_rectangles"], used_rect)
                new_cont["used_weight"] += box["weightPerRoll"]
                new_cont["flat_stack_height"] = z + box["height_3d"] + belt_buffer
                used_rect = {"x": x, "y": y,
                             "width": box["base_dims"][0],
                             "height": box["base_dims"][1]}
                new_free = []
                for fr in new_cont["free_rectangles"]:
                    if rects_intersect(fr, used_rect):
                        new_free.extend(subtract_rect(fr, used_rect))
                    else:
                        new_free.append(fr)
                new_cont["free_rectangles"] = new_free
                containers.append(new_cont)
                placed = True

            if placed:
                continue

        effective_width = box["base_dims"][0] + belt_buffer
        effective_length = box["base_dims"][1] + belt_buffer
        if box["weightPerRoll"] > forklift_limit:
            if box["id"] not in st.session_state["heavy_dialog_seen"]:
                heavy_belt_dialog(box["spec"], forklift_limit)
                st.session_state["heavy_dialog_seen"].add(box["id"])
            rejected_belts.append(box)
            continue
        for cont in containers:
            if cont["used_weight"] + box["weightPerRoll"] > container["max_load"]:
                continue
            item_normal = {"width": effective_width, "height": effective_length, "orientation": 0}
            item_rotated = {"width": effective_length, "height": effective_width, "orientation": math.pi / 2}
            if box["belt_width"] > container["width"]:
                free_rect = choose_placement(cont["free_rectangles"], item_rotated)
                chosen_item = item_rotated
            else:
                free_rect = choose_placement(cont["free_rectangles"], item_normal)
                chosen_item = item_normal
                if free_rect is None and allow_rotation:
                    free_rect = choose_placement(cont["free_rectangles"], item_rotated)
                    if free_rect is not None:
                        chosen_item = item_rotated
            if free_rect is None:
                continue
            if box.get("itemType") == "object":
                x = free_rect["x"] + belt_buffer
                y = free_rect["y"] + belt_buffer
            else:
                x = free_rect["x"]
                y = free_rect["y"]
            box["position"] = (x, y, belt_buffer)

            box["placed_dims"] = (chosen_item["width"], chosen_item["height"])
            box["rotation_angle"] = chosen_item["orientation"]
            box["initialPos"] = (free_rect["x"] + chosen_item["width"] / 2,
                                 free_rect["y"] + chosen_item["height"] / 2)
            cont["boxes"].append(box)
            cont["used_weight"] += box["weightPerRoll"]
            free_rect["placed"] = {"width": chosen_item["width"], "height": chosen_item["height"]}
            cont["free_rectangles"] = update_free_rectangles(cont["free_rectangles"], free_rect)
            placed = True
            break
        if not placed:
            new_cont = init_container(container)
            new_cont["id"] = len(containers) + 1
            if box["weightPerRoll"] > container["max_load"]:
                st.error("Belt to heavy for current container setting: " + box["spec"])
                rejected_belts.append(box)
                continue
            effective_width = box["base_dims"][0] + belt_buffer
            effective_length = box["base_dims"][1] + belt_buffer
            item_normal = {"width": effective_width, "height": effective_length, "orientation": 0}
            item_rotated = {"width": effective_length, "height": effective_width, "orientation": math.pi / 2}
            if box["belt_width"] > container["width"]:
                free_rect = choose_placement(new_cont["free_rectangles"], item_rotated)
                chosen_item = item_rotated
            else:
                free_rect = choose_placement(new_cont["free_rectangles"], item_normal)
                chosen_item = item_normal
                if free_rect is None and allow_rotation:
                    free_rect = choose_placement(new_cont["free_rectangles"], item_rotated)
                    if free_rect is not None:
                        chosen_item = item_rotated
            if free_rect is None:
                st.error("Belt doesn't fit into container " + box["spec"])
                rejected_belts.append(box)
                continue
            if box.get("itemType") == "object":
                x = free_rect["x"] + belt_buffer
                y = free_rect["y"] + belt_buffer
            else:
                x = free_rect["x"]
                y = free_rect["y"]
            box["position"] = (x, y, belt_buffer)

            box["placed_dims"] = (chosen_item["width"], chosen_item["height"])
            box["rotation_angle"] = chosen_item["orientation"]
            box["initialPos"] = (free_rect["x"] + chosen_item["width"] / 2,
                                 free_rect["y"] + chosen_item["height"] / 2)
            new_cont["boxes"].append(box)
            new_cont["used_weight"] += box["weightPerRoll"]
            free_rect["placed"] = {"width": chosen_item["width"], "height": chosen_item["height"]}
            new_cont["free_rectangles"] = update_free_rectangles(new_cont["free_rectangles"], free_rect)
            containers.append(new_cont)

    for cont in containers:
        new_boxes = []
        for box in cont["boxes"]:
            if box.get("belt_type") == "chevron" and "belts" in box:
                z = box["position"][2]
                for orig in box["belts"]:
                    b = orig.copy()
                    b["position"] = (box["position"][0], box["position"][1], z)
                    z += orig["height_3d"] + belt_buffer
                    b["placed_dims"] = orig["base_dims"]
                    b["rotation_angle"] = box.get("rotation_angle", 0)
                    b["containerId"] = cont["id"]
                    new_boxes.append(b)
            else:
                new_boxes.append(box)
        cont["boxes"] = new_boxes

    for cont in containers:
        new_boxes = []
        for box in cont["boxes"]:
            if box.get("itemType") == "object" and "belts" in box:
                z = box["position"][2]
                for orig in box["belts"]:
                    b = orig.copy()
                    b["position"] = (box["position"][0], box["position"][1], z)
                    z += orig["height_3d"] + belt_buffer
                    b["placed_dims"] = orig["base_dims"]
                    b["rotation_angle"] = box.get("rotation_angle", 0)
                    b["containerId"] = cont["id"]
                    new_boxes.append(b)
            else:
                new_boxes.append(box)
        cont["boxes"] = new_boxes

    return containers, rejected_belts



def get_threejs_html_all(containers, container_dims, scale=100):
    gap_m = 1.5
    gap_px = gap_m * scale
    containerPositions = []
    for i in range(len(containers)):
        offset_x = i * (container_dims["width"] * scale + gap_px)
        containerPositions.append(offset_x)
    objects_data = []
    for i, cont_obj in enumerate(containers):
        offset_x = containerPositions[i]
        for box in cont_obj["boxes"]:
            pos = box["position"]
            if box.get("itemType", "") == "object":

                let_width = box["base_dims"][0]
                let_length = box["base_dims"][1]
                let_height = box["height_3d"]
                cx = (pos[0] + let_width / 2) * scale + offset_x
                cz = (pos[1] + let_length / 2) * scale
                cy = (pos[2] + let_height / 2) * scale
                objects_data.append({
                    "cx": cx,
                    "cy": cy,
                    "cz": cz,
                    "width": let_width * scale,
                    "depth": let_length * scale,
                    "height": let_height * scale,
                    "color": box.get("color", "#FF0000"),
                    "rotation": box.get("rotation_angle", 0),
                    "spec": box.get("spec", ""),
                    "weightPerRoll": box["weightPerRoll"],
                    "initialPos": box.get("initialPos", [0, 0]),
                    "containerId": cont_obj["id"],
                    "itemType": "object"
                })
            else:
                dims = box.get("placed_dims", box.get("base_dims"))
                cx = (pos[0] + dims[0] / 2) * scale + offset_x
                cz = (pos[1] + dims[1] / 2) * scale
                if box.get("flat", False):
                    cy = (pos[2] + box["height_3d"] / 2) * scale
                elif box.get("isOval", False):
                    cy = (0.04 + pos[2] + box["ovalHeight"] / 2) * scale
                else:
                    cy = (pos[2] + box["rollDiameter"] / 2) * scale
                objects_data.append({
                    "cx": cx,
                    "cy": cy,
                    "cz": cz,
                    "relativePos": pos,
                    "isOval": box.get("isOval", False),
                    "radius": (box["rollDiameter"] / 2) * scale,
                    "diameter": box["rollDiameter"],
                    "height": box["belt_width"] * scale,
                    "color": box.get("color", "#FF0000"),
                    "rotation": box.get("rotation_angle", 0),
                    "spec": box.get("spec", ""),
                    "belt_length": box["length"],
                    "weightPerRoll": box["weightPerRoll"],
                    "initialPos": box.get("initialPos", [0, 0]),
                    "containerId": cont_obj["id"],
                    "core_diameter": core_diameter,
                    "belt_type": box.get("belt_type", "standard"),
                    "max_load": custom_max_load,
                    "radiusX": (box["base_dims"][0] / 2) * scale,
                    "radiusZ": (box["base_dims"][1] / 2) * scale,
                    "flat": box.get("flat", False),
                    "ovalHeight": box.get("ovalHeight", 0) * scale,
                    "ovalRollLength": box.get("ovalRollLength", 0) * scale
                })

    container_centers = []
    for i, offset_x in enumerate(containerPositions):
        center_x = offset_x + (container_dims["width"] * scale) / 2
        center_y = (container_dims["height"] * scale) / 2
        center_z = (container_dims["length"] * scale) / 2
        container_centers.append({
            "id": i + 1,
            "center": [center_x, center_y, center_z]
        })
    objectsDataJSON = json.dumps(objects_data)
    containerCentersJSON = json.dumps(container_centers)
    html_template = f"""
             <!DOCTYPE html>
             <html lang="de">
             <head>
               <meta charset="UTF-8">
               <title>3D Container Viewer – Alle Container</title>
               <style>
                 html {{border-radius: 20px; }}
                 body {{ margin: 0; overflow: hidden; border-radius: 20px; }}
                 #canvas-container {{ position: relative; border-radius: 20px;}}
                 canvas {{ display: block; border-radius: 20px; }}
                 #buttons-container {{
                     position: absolute;
                     bottom: 10px;
                     left: 10px;
                     z-index: 100;
                     padding: 5px;
                     border-radius: 5px;
                     max-width: 75%;
                     color: white;
                     background: black;
                 }}
                 #buttons-container button {{
                     margin: 3px;
                     padding: 5px 10px;
                     border: 1px solid rgb(38, 39, 48);
                     color: white;
                     background-color: rgb(38, 39, 48);
                     border-radius: 5px;
                 }}
                 #transform-mode-buttons {{
                     margin: 3px;
                     padding: 5px 10px;
                     color: white;
                     background: rgb(14, 17, 23);
                     border-radius: 5px;
                     position: absolute; 
                     top: 10px; 
                     left: 10px; 
                     z-index: 200; 
                 }}
                 #transform-mode-buttons button {{
                     margin: 3px;
                     padding: 5px 10px;
                     border: 1px solid rgb(38, 39, 48);
                     color: white;
                     background-color: rgb(38, 39, 48);
                     border-radius: 5px;
                 }}


               </style>
             </head>
             <body>
               <div id="canvas-container"></div>
               <div id="transform-mode-buttons">
                   <button id="btn-translate">Translate</button>
                   <button id="btn-rotate">Rotate</button>
                   <button id="btn-toggleCamera">Camera: Perspective</button>
                   <button id="btn-isolationToggle">Isolation: Off</button>
                   <button id="toggleIndicators">Weight Indicators OFF</button>
                   <button id="btn-save" style="display: none; margin: 3px; padding: 5px 10px; border: 1px solid rgb(38,39,48); color: white; background-color: rgb(38,39,48); border-radius: 5px;">Save Changes</button>

               </div>
               <div id="buttons-container"></div>
               <script type="importmap">
                       {{
                 "imports": {{
                   "three": "https://unpkg.com/three@0.169.0/build/three.module.js",
                   "three/examples/jsm/controls/OrbitControls.js": "https://unpkg.com/three@0.169.0/examples/jsm/controls/OrbitControls.js",
                   "three/examples/jsm/controls/TransformControls.js": "https://unpkg.com/three@0.169.0/examples/jsm/controls/TransformControls.js"
                 }}
               }}
               </script>



               <script type="module">
                 import * as THREE from "three";
                 import {{ OrbitControls }} from "three/examples/jsm/controls/OrbitControls.js";
                 import {{ TransformControls }} from "three/examples/jsm/controls/TransformControls.js";
                 import {{ ViewportGizmo }} from "https://unpkg.com/three-viewport-gizmo@2.0.2/dist/three-viewport-gizmo.js";
                 // ------------------ BASIS ------------------
                 const scale = {scale};
                 const contWidth = {container_dims["width"]} * scale;
                 const contHeight = {container_dims["height"]} * scale;
                 const contLength = ({container_dims["length"]} + {0.12}) * scale;
                 const scene = new THREE.Scene();
                 const weightIndicatorsData = [];
                 let   weightIndicatorsGroup = null;
                 scene.add(new THREE.AmbientLight(0x777777));
                 const directionalLight = new THREE.DirectionalLight(0xffffff, 0.6);
                 directionalLight.position.set(3, 5, 1);
                 scene.add(directionalLight);
                 scene.background = new THREE.Color(0x0e1117);
                 const renderer = new THREE.WebGLRenderer({{ antialias: true }});
                 renderer.setSize(window.innerWidth, window.innerHeight);
                 document.getElementById("canvas-container").appendChild(renderer.domElement);
                 // --- Kameras erstellen ---
                 const perspectiveCamera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 1, 10000);
                 perspectiveCamera.position.set(contLength * 1.5, contHeight * 1.5, contWidth * 1.5);
                 const aspect = window.innerWidth / window.innerHeight;
                 const d = contLength;
                 const orthographicCamera = new THREE.OrthographicCamera(-d * aspect, d * aspect, d, -d, 1, 10000);
                 orthographicCamera.position.copy(perspectiveCamera.position);
                 orthographicCamera.lookAt(new THREE.Vector3(contWidth / 2, contHeight / 2, contLength / 2));
                 let currentCamera = perspectiveCamera;
                 const controls = new OrbitControls(currentCamera, renderer.domElement);

                 controls.minPolarAngle = 0;
                 controls.maxPolarAngle = Math.PI / 2;

                   controls.addEventListener("change", () => {{
                   if (controls.target.y < 0) {{
                   const diff = -controls.target.y;
                   controls.target.y = 0;
                   currentCamera.position.y += diff;
                   if (currentCamera.position.y < 0) {{
                     currentCamera.position.y = 0;
                   }}
                 }}
               }});

        let GizmoOptions = {{
          type: "cube",
          size: 130,
          placement: "top-right",
          resolution: 512,
          lineWidth: 4,
          radius: 0.2,
          smoothness: 18,
          animated: true,
          speed: 1,
          background: {{
            enabled: true,
            color: "#06091f",
            opacity: 1,
            hover: {{
              color: "#10163E",
              opacity: 1
            }}
          }},
          font: {{
            family: "sans-serif",
            weight: 600,
          }},
          offset: {{
            top: 10,
            left: 10,
            bottom: 10,
            right: 10
          }},
          corners: {{
            enabled: true,
            color: "#466193",
            opacity: 1,
            scale: 0.2,
            radius: 1,
            smoothness: 18,
            hover: {{
              color: "#768EB5",
              opacity: 1,
              scale: 0.225
            }}
          }},
          edges: {{
            enabled: true,
            color: "#262730",
            opacity: 0,
            radius: 0.125,
            smoothness: 18,
            scale: 1,
            hover: {{
              color: "#262730",
              opacity: 1,
              scale: 1
            }}
          }},
          x: {{
            enabled: true,
            color: "#213A7A",
            opacity: 1,
            scale: 0.7,
            labelColor: "#ffffff",
            line: false,
            border: {{
              size: 0,
              color: "#DDDDDD"
            }},
            hover: {{
              color: "#466193",
              labelColor: "#ffffff",
              opacity: 1,
              scale: 0.7,
              border: {{
                size: 0,
                color: "#DDDDDD"
              }}
            }},
            label: "Right"
          }},
          y: {{
            enabled: true,
            color: "#213A7A",
            opacity: 1,
            scale: 0.7,
            labelColor: "#ffffff",
            line: false,
            border: {{
              size: 0,
              color: "#DDDDDD"
            }},
            hover: {{
              color: "#466193",
              labelColor: "#ffffff",
              opacity: 1,
              scale: 0.7,
              border: {{
                size: 0,
                color: "#DDDDDD"
              }}
            }},
            label: "Top"
          }},
          z: {{
            enabled: true,
            color: "#213A7A",
            opacity: 1,
            scale: 0.7,
            labelColor: "#ffffff",
            line: false,
            border: {{
              size: 0,
              color: "#DDDDDD"
            }},
            hover: {{
              color: "#466193",
              labelColor: "#ffffff",
              opacity: 1,
              scale: 0.7,
              border: {{
                size: 0,
                color: "#DDDDDD"
              }}
            }},
            label: "Door"
          }},
          nx: {{
            enabled: true,
            color: "#213A7A",
            opacity: 1,
            labelColor: "#ffffff",
            scale: 0.7,
            line: false,
            border: {{
              size: 0,
              color: "#DDDDDD"
            }},
            hover: {{
              scale: 0.7,
              color: "#466193",
              labelColor: "#ffffff",
              opacity: 1,
              border: {{
                size: 0,
                color: "#DDDDDD"
              }}
            }},
            label: "Left"
          }},
          ny: {{
            enabled: true,
            color: "#213A7A",
            opacity: 1,
            labelColor: "#ffffff",
            scale: 0.7,
            line: false,
            border: {{
              size: 0,
              color: "#DDDDDD"
            }},
            hover: {{
              scale: 0.7,
              color: "#466193",
              labelColor: "#ffffff",
              opacity: 1,
              border: {{
                size: 0,
                color: "#DDDDDD"
              }}
            }},
            label: "Bottom"
          }},
          nz: {{
            enabled: true,
            color: "#213A7A",
            opacity: 1,
            labelColor: "#ffffff",
            scale: 0.7,
            line: false,
            border: {{
              size: 0,
              color: "#DDDDDD"
            }},
            hover: {{
              scale: 0.7,
              color: "#466193",
              labelColor: "#ffffff",
              opacity: 1,
              border: {{
                size: 0,
                color: "#DDDDDD"
              }}
            }},
            label: "Back"
          }},
          isSphere: false
        }};

                 let transformControls = new TransformControls(currentCamera, renderer.domElement);
                 scene.add(transformControls.getHelper());
                 const gizmo = new ViewportGizmo(currentCamera, renderer, GizmoOptions);
                 gizmo.attachControls(controls);

                 controls.mouseButtons = {{
                   LEFT: THREE.MOUSE.PAN,
                   MIDDLE: THREE.MOUSE.DOLLY,
                   RIGHT: THREE.MOUSE.ROTATE
                 }};
                 const gridHelper = new THREE.GridHelper(99999, 400, 0x262730, 0x34353d);
                 scene.add(gridHelper);

               function createContainerLabel(text, position) {{
                 const canvas = document.createElement('canvas');
                 canvas.width = 256;
                 canvas.height = 64;
                 const context = canvas.getContext('2d');
                 context.font = "Bold 48px Arial";
                 context.fillStyle = "white";
                 context.textAlign = "center";
                 context.textBaseline = "middle";
                 context.fillText(text, canvas.width / 2, canvas.height / 2);
                 const texture = new THREE.CanvasTexture(canvas);
                 const spriteMaterial = new THREE.SpriteMaterial({{ map: texture, transparent: true }});
                 const sprite = new THREE.Sprite(spriteMaterial);
                 // Passe die Größe des Sprites an (anpassen nach Bedarf)
                 sprite.scale.set(250, 60, 5);
                 sprite.position.copy(position);
                 return sprite;
               }}

               // ------------------ CONTAINERS ------------------
               const containersGroup = new THREE.Group();
               const gap = {gap_px};
               const containerCameras = [];
               const containerImages = [];
               const containerLabels = [];
               const numContainers = {len(containers)};
               for (let i = 0; i < numContainers; i++) {{
                 const offsetX = i * (contWidth + gap);
                 const geometry = new THREE.BoxGeometry(contWidth, contHeight, contLength);
                 const material = new THREE.MeshLambertMaterial({{ color: "#808080", transparent: true, opacity: 0.3 }});
                 const containerMesh = new THREE.Mesh(geometry, material);
                 containerMesh.position.set(offsetX + contWidth / 2, contHeight / 2, contLength / 2);

                 const edges = new THREE.EdgesGeometry(geometry);
                 const edgeMaterial = new THREE.LineBasicMaterial({{ color: "#808080", transparent: true, opacity: 0.9 }});
                 const edgeLines = new THREE.LineSegments(edges, edgeMaterial);
                 containerMesh.add(edgeLines);

                 containerMesh.raycast = function() {{ /* nothing */ }};
                 containerMesh.userData.containerId = i + 1;
                 containersGroup.add(containerMesh);

                 // --------------TOP-VIEW KAMERA------------------
                 const margin = 20; // optional, damit der Container vollständig im Bild ist
                 const left = -contWidth / 2 - margin;
                 const right = contWidth / 2 + margin;
                 const top = contLength / 2 + margin;
                 const bottom = -contLength / 2 - margin;
                 const containerCamera = new THREE.OrthographicCamera(left, right, top, bottom, 1, 10000);
                 containerCamera.position.set(containerMesh.position.x, contHeight * 3, containerMesh.position.z);
                 containerCamera.lookAt(new THREE.Vector3(containerMesh.position.x, 0, containerMesh.position.z));

                 containerMesh.userData.containerCamera = containerCamera;
                 containerCameras.push(containerCamera);
                 const imageData = captureImageFromCamera(containerMesh.userData.containerCamera);
                 containerImages.push(imageData);

                 const labelPos = new THREE.Vector3(containerMesh.position.x, 10, containerMesh.position.z+330);
                 const label = createContainerLabel((i + 1).toString(), labelPos);
                 label.userData.containerId = i + 1;
                 containerLabels.push(label);
                 scene.add(label);
               }}
                 if (window.Streamlit) {{
                  Streamlit.setComponentValue({{
                    refreshTopview: true,
                    images: containerImages
                  }});
                }}


            scene.add(containersGroup);
            // ------------------ BELTS (Zylinder) & OBJECTS (Box) ------------------
            const objectsData = JSON.parse('{objectsDataJSON}');
            const selectableObjects = [];
            objectsData.forEach((obj, index) => {{
              let mesh;
              if (obj.itemType && obj.itemType === "object") {{
                const geometry = new THREE.BoxGeometry(obj.width, obj.height, obj.depth);
                const material = new THREE.MeshLambertMaterial({{ color: obj.color }});
                mesh = new THREE.Mesh(geometry, material);
                mesh.rotation.y = obj.rotation;
                mesh.position.set(obj.cx, obj.cy, obj.cz);
              }} else {{
                const radialSegments = (obj.belt_type === "steelcord" || obj.belt_type === "chevron") ? 10 : 32;
                let geometry = new THREE.CylinderGeometry(obj.radius, obj.radius, obj.height, radialSegments);
                geometry.computeBoundingBox();

                  if (obj.isOval) {{
                     geometry = new THREE.CylinderGeometry(1, 1, obj.ovalHeight, radialSegments);
                     geometry.scale(obj.radiusX, 1, obj.radiusZ);
                   }} else {{
                     geometry = new THREE.CylinderGeometry(obj.radius, obj.radius, obj.height, radialSegments);
                   }}



                const material = new THREE.MeshLambertMaterial({{ color: obj.color }});
                mesh = new THREE.Mesh(geometry, material);

                if (obj.flat) {{
                  mesh.rotation.z = 0;
                  mesh.rotation.y = 0;
                }} else {{
                  mesh.rotation.z = Math.PI / 2;
                  mesh.rotation.y = obj.rotation;
                }}
                mesh.position.set(obj.cx, obj.cy, obj.cz);
              }}

              mesh.userData = {{
                spec: obj.spec,
                belt_length: obj.belt_length,
                weightPerRoll: obj.weightPerRoll,
                core_diameter: obj.core_diameter,
                diameter: obj.diameter,
                relativePos: obj.relativePos,
                containerId: obj.containerId,
                itemType: obj.itemType ? obj.itemType : "belt" // Standard: "belt"
              }};
              scene.add(mesh);
              selectableObjects.push(mesh);

              if (!obj.itemType || obj.itemType !== "object") {{
                weightIndicatorsData.push({{
                  position: new THREE.Vector3(obj.cx, obj.cy - (obj.radius ? obj.radius : 0), obj.cz),
                  weight: obj.weightPerRoll,
                  belt: mesh,
                  offset: new THREE.Vector3(0, -(obj.radius ? obj.radius : 0), 0)
                }});
              }}
            }});

            let currentSelected = null;

            function selectObject(object) {{
              if (currentSelected !== object) {{
                if (currentSelected) removeOutline(currentSelected);
                currentSelected = object;
                addOutline(object);
                const offset = new THREE.Vector3();
                offset.copy(currentCamera.position).sub(controls.target);
                controls.target.copy(object.position);
                currentCamera.position.copy(controls.target).add(offset);
                controls.update();
              }}
            }}





                 // ------------------ TRANSFORM CONTROLS ------------------
                 transformControls.setMode("translate");
                 transformControls.setSize(0.7);
                 transformControls.setSpace("local");
                 transformControls.setRotationSnap(THREE.MathUtils.degToRad(45));
                 const btnTranslate = document.getElementById("btn-translate");
                 const btnRotate = document.getElementById("btn-rotate");
                 const btnToggleCamera = document.getElementById("btn-toggleCamera");
                 const btnIsolationToggle = document.getElementById("btn-isolationToggle");



                 btnTranslate.addEventListener("click", () => {{
                   transformControls.setMode("translate");
                   transformControls.setRotationSnap(null);
                 }});
                 btnRotate.addEventListener("click", () => {{
                   transformControls.setMode("rotate");
                   transformControls.setRotationSnap(THREE.Math.degToRad(45));
                 }});

        transformControls.addEventListener('dragging-changed', function (event) {{
            controls.enabled = !event.value;

            if (!event.value && currentSelected) {{    
                const containerIndex = getContainerIndexForObject(currentSelected, containersGroup);
                document.getElementById("btn-save").style.display = "block";
                if (containerIndex !== null) {{
                    const offsetX = containerIndex * (contWidth + gap);
                    const bbox    = new THREE.Box3().setFromObject(currentSelected);
                    const size    = new THREE.Vector3();
                    bbox.getSize(size);

                    const relX = (currentSelected.position.x - offsetX - size.x / 2) / scale;
                    const relZ = (currentSelected.position.z - size.z  / 2) / scale;
                    const relY = (currentSelected.position.y - size.y / 2) / scale;

                    currentSelected.userData.relativePos  = [relX, relZ, relY];
                    currentSelected.userData.containerId  = containerIndex + 1;
                }} else {{
                    currentSelected.userData.relativePos = ["n/a", "n/a", "n/a"];
                }}


                if (window.Streamlit) {{
                    Streamlit.setComponentValue({{
                        beltId:     currentSelected.userData.id,
                        relativePos: currentSelected.userData.relativePos,
                        rotation:   currentSelected.rotation.y,
                        containerId: currentSelected.userData.containerId
                    }});
                }}

                /* ---------- Top-View updaten ---------- */
                  // <- hier genügt ein Aufruf
            }}
                }});





            transformControls.addEventListener('objectChange', function () {{
              if (currentSelected) {{
                if (transformControls.getMode() === 'translate') {{
                  const box = new THREE.Box3().setFromObject(currentSelected);
                  if (box.min.y < 0.05) {{
                    currentSelected.position.y += 0.05 - box.min.y;
                    controls.target.y = Math.max(controls.target.y, 0.05);
                  }}
                }}
                let containerIndex = getContainerIndexForObject(currentSelected, containersGroup);
                let offsetX = 0;
                if (containerIndex !== null) {{
                  offsetX = containerIndex * (contWidth + gap);
                  let bbox = new THREE.Box3().setFromObject(currentSelected);
                  let size = new THREE.Vector3();
                  bbox.getSize(size);
                  let relX = (currentSelected.position.x - offsetX - size.x / 2) / scale;
                  let relZ = (currentSelected.position.z - size.z / 2) / scale;
                  let relY = (currentSelected.position.y - size.y / 2) / scale;
                  currentSelected.userData.relativePos = [relX, relZ, relY];
                  currentSelected.userData.containerId = containerIndex + 1;
                }} else {{
                  currentSelected.userData.relativePos = ["n/a", "n/a", "n/a"];
                }}
              }}
            }});




        document.getElementById("btn-save").addEventListener("click", () => {{
          if (window.Streamlit && currentSelected){{
            Streamlit.setComponentValue({{
              beltUpdate: {{
                id:          currentSelected.userData.id,
                relativePos: currentSelected.userData.relativePos, // [x,z,y]
                rotation:    currentSelected.rotation.y,           // rad
                containerId: currentSelected.userData.containerId
              }}
            }});
          }}
          document.getElementById("btn-save").style.display = "none";
        }});






                 if (selectableObjects.length > 0) {{
                   transformControls.attach(selectableObjects[0]);
                   selectObject(selectableObjects[0])
                 }}
                 renderer.domElement.addEventListener('dblclick', function(event) {{
                     const rect = renderer.domElement.getBoundingClientRect();
                     const mouse = new THREE.Vector2();
                     mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
                     mouse.y = - ((event.clientY - rect.top) / rect.height) * 2 + 1;

                     const raycaster = new THREE.Raycaster();
                     raycaster.setFromCamera(mouse, currentCamera);
                     const intersects = raycaster.intersectObjects(selectableObjects.filter(obj => obj.visible), true);

                     if (intersects.length > 0) {{
                       const hitObject = intersects[0].object;
                       // Nur wenn sichtbar, selektieren
                       if (hitObject.visible) {{
                         transformControls.attach(hitObject);
                         selectObject(hitObject);
                       }} else {{
                         clearSelection();
                       }}
                     }} else {{
                       clearSelection();
                     }}
                   }});


               btnToggleCamera.addEventListener("click", () => {{
                     if (currentCamera === perspectiveCamera) {{
                       // Synchronisiere Orthographic Camera mit Perspective Camera
                       orthographicCamera.position.copy(perspectiveCamera.position);
                       orthographicCamera.quaternion.copy(perspectiveCamera.quaternion);
                       orthographicCamera.updateProjectionMatrix();
                       currentCamera = orthographicCamera;
                       btnToggleCamera.innerText = "Camera: Orthographic";
                     }} else {{
                       // Synchronisiere Perspective Camera mit Orthographic Camera
                       perspectiveCamera.position.copy(orthographicCamera.position);
                       perspectiveCamera.quaternion.copy(orthographicCamera.quaternion);
                       perspectiveCamera.updateProjectionMatrix();
                       currentCamera = perspectiveCamera;
                       btnToggleCamera.innerText = "Camera: Perspective";
                     }}

                     // Aktualisiere OrbitControls mit der neuen Kamera
                     controls.object = currentCamera;
                     gizmo.camera = currentCamera;
                     transformControls.camera = currentCamera;

                     controls.update();
                     gizmo.attachControls(controls);
                     transformControls.update(); 

                     // Falls ein Objekt aktuell ausgewählt ist, wieder anhängen
                     if (currentSelected) {{
                         transformControls.attach(currentSelected);
                     }}

               }});

                function getBeltFromObject(obj) {{
                  while (obj && (!obj.userData || obj.userData.relativePos === undefined)) {{
                    obj = obj.parent;
                  }}
                  return obj;
                }}

                function refreshContainerScreenshots() {{

                }}


                function getContainerIndexForObject(object, containersGroup) {{
                  const bbox = new THREE.Box3().setFromObject(object);
                  for (let i = 0; i < containersGroup.children.length; i++) {{
                    const containerMesh = containersGroup.children[i];
                    const containerBox = new THREE.Box3().setFromObject(containerMesh);
                    if (containerBox.intersectsBox(bbox)) {{
                      return i;
                    }}
                  }}
                  return null;
                }}

                function updateSpriteVisibility() {{
                  if (isIsolationMode && selectedContainerId !== null) {{
                    containerLabels.forEach(label => {{
                      label.visible = (label.userData.containerId === selectedContainerId);
                    }});
                  }} else {{
                    containerLabels.forEach(label => {{
                      label.visible = true;
                    }});
                  }}
                }}


                 // ------------------ TOOLTIP ------------------
                 const tooltip = document.createElement("div");
                 tooltip.style.position = "absolute";
                 tooltip.style.background = "rgba(0, 0, 0, 0.7)";
                 tooltip.style.color = "#fff";
                 tooltip.style.padding = "5px";
                 tooltip.style.borderRadius = "5px";
                 tooltip.style.display = "none";
                 tooltip.style.pointerEvents = "none";
                 tooltip.style.fontSize = "14px";
                 document.body.appendChild(tooltip);

                 renderer.domElement.addEventListener('mousemove', function(event) {{
                      const rect = renderer.domElement.getBoundingClientRect();
                      const mouse = new THREE.Vector2();
                      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
                      mouse.y = - ((event.clientY - rect.top) / rect.height) * 2 + 1;

                      const raycaster = new THREE.Raycaster();
                      raycaster.setFromCamera(mouse, currentCamera);
                      const intersects = raycaster.intersectObjects(selectableObjects.filter(obj => obj.visible), true);

                      if (intersects.length > 0) {{
                        let obj = intersects[0].object;
                        const beltObj = getBeltFromObject(obj);
                       // console.log("Raycaster-Triple:", {{ raw: obj, belt: beltObj }});
                        if (!beltObj) {{
                          tooltip.style.display = 'none';
                          return;
                        }}

                        tooltip.style.display = 'block';
                        tooltip.innerHTML =
                          "Spec: " + beltObj.userData.spec + "<br>" +
                          "Length: " + beltObj.userData.belt_length + "m<br>" +
                          "CoreDiameter: " + beltObj.userData.core_diameter + "m<br>" +
                          "Diameter: " + beltObj.userData.diameter + "m<br>" +
                          "Weight: " + beltObj.userData.weightPerRoll + "kg<br>" +
                          "Position: (" +
                            (beltObj.userData.relativePos?.[0]?.toFixed(2) ?? "-") + ", " +
                            (beltObj.userData.relativePos?.[1]?.toFixed(2) ?? "-") + ", " +
                            (beltObj.userData.relativePos?.[2]?.toFixed(2) ?? "-") +
                          ")";


                        tooltip.style.left = (event.clientX + 10) + "px";
                        tooltip.style.top = (event.clientY + 10) + "px";
                      }} else {{
                        tooltip.style.display = 'none';
                      }}
                    }});


                 let isIsolationMode = false;
                 btnIsolationToggle.addEventListener("click", () => {{
                     isIsolationMode = !isIsolationMode;
                     btnIsolationToggle.innerText = isIsolationMode ? "Isolation: On" : "Isolation: Off";
                     if (isIsolationMode) {{
                       if (selectedContainerId !== null) {{
                         containersGroup.children.forEach(containerMesh => {{
                           containerMesh.visible = (containerMesh.userData.containerId === selectedContainerId);
                         }});
                         selectableObjects.forEach(belt => {{
                           belt.visible = (belt.userData.containerId === selectedContainerId);
                         }});
                         containerLabels.forEach(label => {{
                           label.visible = (label.userData.containerId === selectedContainerId);

                         }});
                       }}
                     }} else {{
                       containersGroup.children.forEach(containerMesh => containerMesh.visible = true);
                       selectableObjects.forEach(belt => belt.visible = true);
                       containerLabels.forEach(label => {{
                         label.visible = true;
                       }});
                     }}
                   }});


                 const containerCenters = JSON.parse('{containerCentersJSON}');
                 const buttonsContainer = document.getElementById("buttons-container");

                 let selectedContainerId = null;

                   containerCenters.forEach(container => {{
                     const btn = document.createElement("button");
                     btn.innerText = "Container " + container.id;
                     btn.addEventListener("click", function() {{
                       transformControls.detach();
                       clearSelection();
                       selectedContainerId = container.id;
                       const center = container.center;
                       const offset = new THREE.Vector3().subVectors(currentCamera.position, controls.target);
                       const newTarget = new THREE.Vector3(center[0], center[1], center[2]);
                       const defaultDistance = 1000;
                       offset.setLength(defaultDistance);
                       controls.target.copy(newTarget);
                       currentCamera.position.copy(newTarget).add(offset);
                       currentCamera.updateProjectionMatrix();

                       if (isIsolationMode) {{
                         containersGroup.children.forEach(containerMesh => {{
                           containerMesh.visible = (containerMesh.userData.containerId === container.id);
                         }});
                         selectableObjects.forEach(belt => {{
                           belt.visible = (belt.userData.containerId === container.id);
                         }});
                         containerLabels.forEach(label => {{
                           label.visible = (label.userData.containerId === selectedContainerId);

                         }});
                       }} else {{
                         containersGroup.children.forEach(containerMesh => containerMesh.visible = true);
                         selectableObjects.forEach(belt => belt.visible = true);
                         containerLabels.forEach(label => {{
                         label.visible = (label.userData.containerId === selectedContainerId);
                        }});
                       }}
                     }});
                     buttonsContainer.appendChild(btn);
                   }});

                 function findContainerForGurt(gurtBox) {{
                  for (let i = 0; i < containersGroup.children.length; i++) {{
                     const containerMesh = containersGroup.children[i];
                     const cBox = new THREE.Box3().setFromObject(containerMesh);
                     if (cBox.intersectsBox(gurtBox)) {{
                       return containerMesh;
                     }}
                   }}
                   return null;
                 }}

                 function checkCollisions() {{
                   containersGroup.children.forEach(c => {{
                     c.material.color.set("#808080");
                   }});
                   const beltBoxes = selectableObjects.map(mesh => {{
                     mesh.geometry.computeBoundingBox();
                     const worldBox = mesh.geometry.boundingBox.clone();
                     worldBox.applyMatrix4(mesh.matrixWorld);
                     return {{ mesh: mesh, box: worldBox }};
                   }});
                   for (let i = 0; i < beltBoxes.length; i++) {{
                     for (let j = i + 1; j < beltBoxes.length; j++) {{
                       if (beltBoxes[i].box.intersectsBox(beltBoxes[j].box)) {{
                         const c1 = findContainerForGurt(beltBoxes[i].box);
                         const c2 = findContainerForGurt(beltBoxes[j].box);
                         if (c1) c1.material.color.set("yellow");
                         if (c2) c2.material.color.set("yellow");
                       }}
                     }}
                   }}
                   beltBoxes.forEach(beltItem => {{
                     const containerMesh = findContainerForGurt(beltItem.box);
                     if (containerMesh) {{
                       const cBox = new THREE.Box3().setFromObject(containerMesh);
                       if (!cBox.containsBox(beltItem.box)) {{
                         containerMesh.material.color.set("red");
                       }}
                     }}
                   }});
                   const containerWeights = {{}};
                    objectsData.forEach(obj => {{
                      const cId = obj.containerId;
                      if (!containerWeights[cId]) containerWeights[cId] = 0;
                      containerWeights[cId] += obj.weightPerRoll;
                    }});
                    containersGroup.children.forEach(containerMesh => {{
                      const cId = containerMesh.userData.containerId;
                      const containerMaxLoad = objectsData.find(obj => obj.containerId === cId).max_load;
                      if (containerWeights[cId] > containerMaxLoad) {{
                        containerMesh.material.color.set("orange");
                      }}
                    }});
                 }}

                 //----------Weight Indicators------------

                 let showWeightIndicators = false;
                   document.getElementById("toggleIndicators").addEventListener("click", function() {{
                   showWeightIndicators = !showWeightIndicators;
                   this.textContent = showWeightIndicators ? "Weight Indicators ON" : "Weight Indicators OFF";
                 }});

              function updateWeightIndicators() {{
  if (!showWeightIndicators) {{
    if (weightIndicatorsGroup) {{
      scene.remove(weightIndicatorsGroup);
      weightIndicatorsGroup = null;
    }}
    return;
  }}
  const cameraDistance = currentSelected 
       ? currentCamera.position.distanceTo(currentSelected.position) 
       : currentCamera.position.length();
  const hideIndicatorsDistance = 1500;
  if (cameraDistance > hideIndicatorsDistance) {{
    if (weightIndicatorsGroup) {{
      scene.remove(weightIndicatorsGroup);
      weightIndicatorsGroup = null;
    }}
    return;
  }}

  weightIndicatorsData.forEach(ind => {{
    if (ind.belt) {{
      ind.position.copy(ind.belt.position.clone().add(ind.offset));
    }}
  }});

  if (weightIndicatorsGroup) {{
    scene.remove(weightIndicatorsGroup);
    weightIndicatorsGroup = null;
  }}
  const group = new THREE.Group();
  group.name = "weightIndicatorsGroup";


  const groupingRadius = cameraDistance * 0.2;
  const rowThreshold = cameraDistance * 0.1;

  const visibleIndicators = weightIndicatorsData.filter(ind => ind.belt.visible);
  const groups = [];
  visibleIndicators.forEach(ind => {{
    let found = false;
    for (let grp of groups) {{

      if (Math.abs(grp.center.x - ind.position.x) < groupingRadius &&
          Math.abs(grp.center.z - ind.position.z) < rowThreshold) {{
        grp.weight += ind.weight;

        grp.center.x = (grp.center.x * grp.indicators.length + ind.position.x) / (grp.indicators.length + 1);
        grp.center.z = (grp.center.z * grp.indicators.length + ind.position.z) / (grp.indicators.length + 1);
        grp.indicators.push(ind);
        found = true;
        break;
      }}
    }}
    if (!found) {{
      groups.push({{ center: ind.position.clone(), weight: ind.weight, indicators: [ind] }});
    }}
  }});

  groups.forEach(grp => {{
    let arrowLength = 20, labelOffset = new THREE.Vector3(0, -30, 0);
    if (grp.indicators.length > 1) {{
      arrowLength = 80;
      labelOffset = new THREE.Vector3(0, -90, 0);
    }}
    const arrowHelper = new THREE.ArrowHelper(new THREE.Vector3(0, -1, 0), grp.center, arrowLength, 0xffff00);
    group.add(arrowHelper);
    const weightText = grp.weight.toFixed(2) + " kg";
    const labelPosition = grp.center.clone().add(labelOffset);
    const weightLabel = createContainerLabel(weightText, labelPosition);
    const distance = currentCamera.position.distanceTo(labelPosition);
    const scaleFactor = distance / 2000;
    weightLabel.scale.set(250 * scaleFactor, 60 * scaleFactor, 1);
    group.add(weightLabel);
  }});

  scene.add(group);
  weightIndicatorsGroup = group;
}}




                 function animate() {{
                   requestAnimationFrame(animate);
                   controls.update();
                   renderer.render(scene, currentCamera);
                   gizmo.render();
                   checkCollisions();
                   updateWeightIndicators();
                 }}
                 animate();

                 window.addEventListener('resize', function() {{
                   const aspect = window.innerWidth / window.innerHeight;
                   perspectiveCamera.aspect = aspect;
                   perspectiveCamera.updateProjectionMatrix();
                   orthographicCamera.left = -d * aspect;
                   orthographicCamera.right = d * aspect;
                   orthographicCamera.top = d;
                   orthographicCamera.bottom = -d;
                   orthographicCamera.updateProjectionMatrix();
                   renderer.setSize(window.innerWidth, window.innerHeight);
                   gizmo.update();
                 }});

                function addOutline(object) {{
                     if (object.getObjectByName("outline")) return


                     const edges = new THREE.EdgesGeometry(object.geometry)
                     const outlineMaterial = new THREE.LineBasicMaterial({{ color: 0xffff00 }})
                     const outline = new THREE.LineSegments(edges, outlineMaterial)
                     outline.name = "outline"
                     object.add(outline)
                   }}

                   function removeOutline(object) {{
                     const outline = object.getObjectByName("outline")
                     if (outline) {{
                       object.remove(outline)
                     }}
                   }}

                   function clearSelection() {{
                     transformControls.detach();
                     if (currentSelected) {{
                       removeOutline(currentSelected);
                       currentSelected = null;
                     }}
                   }}

                   function captureImageFromCamera(camera) {{
                      const oldCamera = currentCamera;
                      currentCamera = camera;

                      renderer.render(scene, camera);
                      const dataUrl = renderer.domElement.toDataURL("image/png");
                      currentCamera = oldCamera;
                      return dataUrl;
                    }}

                      if (window.Streamlit) {{
                          Streamlit.setComponentValue({{
                            refreshTopview: true,
                            images: containerImages
                          }});
                        }}

               </script>
             </body>
             </html>
             """
    return html_template

# ------------------- Streamlit UI -------------------

st.title("Container-Loading Tool")


@st.cache_data
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()


def set_png_as_page_bg(png_file, overlay_opacity=0.95):
    bin_str = get_base64_of_bin_file(png_file)

    page_bg_img = f'''
    <style>
    [data-testid="stAppViewContainer"] {{
        background: 
            linear-gradient(rgba(14, 17, 23, {overlay_opacity}), rgba(14, 17, 23, {overlay_opacity})),
            url("data:image/png;base64,{bin_str}");
        background-size: cover;
    }}
    </style>
    '''

    st.markdown(page_bg_img, unsafe_allow_html=True)


_topview_component = components.declare_component(
    "topview_component",
    path="static/topview_component"
)


def top_and_side_component(containers, container_dims, scale=100, refresh=True):

    return _topview_component(
        containers=containers,
        container_dims=container_dims,
        scale=scale,
        refreshTopview=refresh,
        default={"top": [], "side": []}
    )



if "belt_updates" not in st.session_state:
    st.session_state["belt_updates"] = {}
if "show_addbelt_confirm" not in st.session_state:
    st.session_state.show_addbelt_confirm = False
if "pending_belt" not in st.session_state:
    st.session_state.pending_belt = None

set_png_as_page_bg('static/Vasco_Hintergrundbild.jpg')

st.sidebar.header("Settings")
container_type = st.sidebar.selectbox("Choose Container:", list(containerData.keys()))
default_load = containerData[container_type]["max_load"]
custom_max_load = st.sidebar.number_input("Max. Container Weight (kg)", value=default_load, step=100)
forklift_limit = st.sidebar.number_input("Max. Forklift Weight (kg)", value=8000, step=100)
allow_rotation = st.sidebar.checkbox("Allow Rotation (3D)", value=True)
center_chevrons = st.sidebar.checkbox("Center Chevrons", value=True)

if st.sidebar.checkbox("Debug Mode"):
    for idx, belt in enumerate(st.session_state.belts):
        with st.expander(f"Belt {idx + 1} – {belt['spec']}"):
            st.json(belt)

with st.sidebar.expander("Add Belt manually"):
    st.header("Conveyor Belt")
    is_oval = st.checkbox("Oval Roll", value=False)
    is_steelcord = st.checkbox("Steelcord", value=False)
    is_ripstop = st.checkbox("Ripstop", value=False)
    spec = st.text_input("Belt-Specification (e.g. 1200 EP500/3-5:2-Y / CE)")
    length_input = st.text_input("Length (m)")
    core_diameter = st.number_input("Core Diameter [m]", value=0.3, format="%.3f")
    if is_oval:
        oval_segment_length = st.number_input("Oval Segment Length [m]", value=0.0, format="%.3f")
    else:
        oval_segment_length = 0
    if is_steelcord:
        steel_cord_diameter = st.number_input("Steel Cord Diameter [mm]", value=0.0, format="%.2f")
    else:
        steel_cord_diameter = 0
    if is_ripstop:
        rip_stop_layers = st.number_input("Rip-Stop Layers", value=0, step=1)
    else:
        rip_stop_layers = 0

    if st.button("Add Belt"):
        belt = parse_belt(spec, length_input, core_diameter, oval_segment_length,
                          steel_cord_diameter, rip_stop_layers, is_oval)
        if belt is not None:
            cont = containerData[container_type]
            w, l = belt["base_dims"]
            fits_footprint = (w <= cont["width"] and l <= cont["length"]) or (
                    allow_rotation and l <= cont["width"] and w <= cont["length"])
            fits_weight = belt["weightPerRoll"] <= forklift_limit and belt["weightPerRoll"] <= cont["max_load"]
            if not (fits_footprint and fits_weight):
                st.session_state.pending_belt = belt
                st.session_state.show_addbelt_confirm = True
            else:
                belt["id"] = st.session_state['belt_id_counter']
                st.session_state['belt_id_counter'] += 1
                st.session_state.belts.append(belt)
                st.success(f"Added Belt: {belt['spec']}")
                st.rerun()


    @st.dialog("Belt too heavy for forklift")
    def heavy_belt_dialog(spec: str, limit: float):
        st.write(f"Belt too heavy for forklift ({limit} kg): {spec}")
        if st.button("OK"):
            st.session_state["show_heavy_dialog"] = False
            st.rerun()


    @st.dialog("Belt too big for container configuration")
    def belt_doesnt_fit(spec: str):
        st.write(f"The Belt is too big: {spec}")
        rejected_belts.append(box)
        if st.button("OK"):
            pass


    @st.dialog("Warning: Belt doesn't fit into container ")
    def addbelt_confirm():
        st.write("The Belt does not fit into the container settings.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Abort"):
                st.session_state.show_addbelt_confirm = False
                st.session_state.pending_belt = None
                st.rerun()
        with c2:
            if st.button("Add anyway"):
                b = st.session_state.pending_belt
                b["id"] = st.session_state['belt_id_counter']
                st.session_state['belt_id_counter'] += 1
                st.session_state.belts.append(b)
                st.session_state.show_addbelt_confirm = False
                st.session_state.pending_belt = None
                st.success(f"Added Belt: {b['spec']}")
                st.rerun()


    if st.session_state.show_addbelt_confirm:
        addbelt_confirm()

with st.sidebar.expander("Add Object manually"):
    st.header("***UNDER CONSTRUCTION***")
    obj_height = st.number_input("Height (m)", value=1.0, format="%.3f", key="obj_height")
    obj_width = st.number_input("Width (m)", value=1.0, format="%.3f", key="obj_width")
    obj_length = st.number_input("Length (m)", value=1.0, format="%.3f", key="obj_length")
    obj_weight = st.number_input("Weight (kg)", value=100.0, step=1.0, format="%.2f", key="obj_weight")

    if st.button("Add object", key="add_object_button"):
        if 'object_id_counter' not in st.session_state:
            st.session_state['object_id_counter'] = 0
        new_object = {
            "spec": f"Object {st.session_state['object_id_counter']}",
            "length": obj_length,
            "belt_width": obj_width,
            "width_mm": obj_width * 1000,
            "base_dims": (obj_width, obj_length),
            "weightPerRoll": obj_weight,
            "height_3d": obj_height,
            "rollDiameter": obj_height,
            "color": get_random_color(),
            "initialPos": [0, 0],
            "is_box": True,
            "itemType": "object"
        }
        st.session_state['object_id_counter'] += 1
        st.session_state.belts.append(new_object)
        st.success(f"Objekt hinzugefügt: {new_object['spec']}")

        cont = containerData[container_type]
        containers, rejected_belts = pack_belts_into_containers(st.session_state.belts, cont, allow_rotation,
                                                                forklift_limit)
        st.session_state["containers"] = containers
        st.session_state["rejected_belts"] = rejected_belts

        st.session_state["last_belts_count"] = len(st.session_state.belts)
        st.session_state["needs_reordering"] = False

with st.sidebar.expander("Other Settings"):
    on = st.toggle("Ambelt Mode")
    if on:
        image = 'static/ambelt_logo.svg'
        st.logo(image, size="large", link='https://www.ambelt.de/', icon_image=None)
    else:
        image = 'static/Vasco Logo fin_white.png'
        st.logo(image, size="large", link='https://vasco-global.com/', icon_image=None)

defaults = {
    "order_meta_set": False,
    "order_num": "",
    "current_date": date.today(),
    "sender": "",
    "receiver": ""
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

uploaded_file = st.file_uploader("Upload Excel-File", type=["xlsx", "xls"])
if uploaded_file is None and st.session_state.get("excel_file_name"):
    st.session_state.pop("excel_file_name", None)
    st.session_state.order_meta_set = False
    st.session_state.order_num = ""
    st.session_state.current_date = date.today()
    st.session_state.sender = ""
    st.session_state.receiver = ""
    st.session_state.belts = []
    st.session_state.rejected_belts = []
    st.session_state.containers = []
    st.session_state.last_belts_count = 0
    st.session_state.belt_id_counter = 0

    st.stop()

if uploaded_file is not None and not st.session_state.order_meta_set:

    @st.dialog("Shipping Details")
    def shipping_dialog():
        st.session_state.order_num = st.text_input(
            "Order Number", value=st.session_state.order_num, key="ord_num")
        st.session_state.current_date = st.date_input(
            "Date", value=st.session_state.current_date, key="ord_date")
        st.session_state.sender = st.text_input(
            "Sender", value=st.session_state.sender, key="ord_sender")
        st.session_state.receiver = st.text_input(
            "Receiver", value=st.session_state.receiver, key="ord_receiver")

        if st.button("Save"):
            st.session_state.order_meta_set = True
            st.rerun()


    shipping_dialog()
    st.stop()

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    df.columns = df.columns.str.strip()
    cont = containerData[container_type]
    cont["max_load"] = custom_max_load
    if st.session_state.get("excel_file_name", "") != uploaded_file.name:
        try:
            for _, row in df.iterrows():

                spec_excel = str(row["Belt Specification"]).strip()
                length_excel = str(row["Length"]).replace("m", "").strip()
                core_diameter_excel = float(row["Core Diameter [m]"])

                val_sc = row.get("Steelcord Cord Diameter [mm] (if Steelcord)", None)
                steel_cord_diameter_excel = float(val_sc) if pd.notna(val_sc) else 0.0

                val_oval = row.get("Oval Segment Length [m] (if Oval)", None)
                oval_segment_length_excel = float(val_oval) if pd.notna(val_oval) else 0.0

                val_rip = row.get("RipStop Layers (if Ripstop)", None)
                rip_stop_layers_excel = int(val_rip) if pd.notna(val_rip) else 0

                is_oval = oval_segment_length_excel > 0

                belt = parse_belt(
                    spec_excel,
                    length_excel,
                    core_diameter_excel,
                    oval_segment_length_excel,
                    steel_cord_diameter_excel,
                    rip_stop_layers_excel,
                    is_oval
                )
                if belt is not None:
                    belt["id"] = st.session_state['belt_id_counter']
                    st.session_state['belt_id_counter'] += 1
                    st.session_state.belts.append(belt)
                    containers, rejected_belts = pack_belts_into_containers(st.session_state.belts, cont,
                                                                            allow_rotation, forklift_limit)

                    st.session_state["containers"] = containers
                    st.session_state["rejected_belts"] = rejected_belts

                    st.session_state["last_belts_count"] = len(st.session_state.belts)
                    st.session_state["needs_reordering"] = False
            st.session_state["excel_file_name"] = uploaded_file.name
        except Exception as e:
            st.error(f"Error while opening the Excel-File: {e}")

st.divider()
col3d, coledit = st.columns([6, 4])

with col3d:
    cont = containerData[container_type]
    cont["max_load"] = custom_max_load

    if ("last_belts_count" not in st.session_state) or (
            st.session_state["last_belts_count"] != len(st.session_state.belts)):
        containers, rejected_belts = pack_belts_into_containers(st.session_state.belts, cont, allow_rotation,
                                                                forklift_limit)
        st.session_state["containers"] = containers
        st.session_state["last_belts_count"] = len(st.session_state.belts)
        st.session_state["needs_reordering"] = False
    else:
        containers = st.session_state["containers"]
        for cont_obj in containers:
            for box in cont_obj["boxes"]:
                matching_belts = [belt for belt in st.session_state.belts if belt.get("id") == box.get("id")]
                if matching_belts:
                    belt = matching_belts[0]
                    box["rollDiameter"] = belt["rollDiameter"]
                    box["weightPerRoll"] = belt["weightPerRoll"]

    html_str = get_threejs_html_all(containers, cont, scale=100)
    st.components.v1.html(html_str, height=700, scrolling=True)
    views = top_and_side_component(containers, cont, scale=100, refresh=True)
    topview_images = views["top"]
    sideview_images = views["side"]

with coledit:
    def dynamic_data_editor(data, key, **kwargs):
        initial_key = f"{key}_initial"
        changed_key = f"{key}_changed"
        if initial_key not in st.session_state:
            st.session_state[initial_key] = data.copy()
        if changed_key not in st.session_state:
            st.session_state[changed_key] = False

        def _on_change():
            st.session_state[changed_key] = True

        editor_value = st.data_editor(data, key=key, on_change=_on_change, **kwargs)
        return editor_value


    def belts_to_df(belts):
        import pandas as pd
        data = []
        for i, belt in enumerate(belts):
            data.append({
                "ID": i,
                "Specification": belt["spec"],
                "Length (m)": belt["length"],
                "Core Diameter (m)": belt.get("core_diameter", 0.3),
            })
        return pd.DataFrame(data).set_index("ID")


    if st.session_state.belts:
        df_belts = belts_to_df(st.session_state.belts)
        df_belts["Remove"] = False
        edited_df = dynamic_data_editor(df_belts, key="belt_editor", use_container_width=True, height=636)

        remove_ids = edited_df[edited_df["Remove"] == True].index.tolist()
        if remove_ids:
            st.session_state.belts = [
                belt for i, belt in enumerate(st.session_state.belts) if i not in remove_ids
            ]
            st.rerun()



        if st.session_state.get("belt_editor_changed", False):
            for idx, row in edited_df.iterrows():
                new_spec = row["Specification"]
                new_length = float(row["Length (m)"])
                new_core = float(row["Core Diameter (m)"])
                st.session_state.belts[int(idx)] = recalc_belt(
                    st.session_state.belts[int(idx)],
                    new_spec,
                    new_length,
                    new_core
                )
            st.session_state["belt_editor_changed"] = False

            containers = st.session_state["containers"]
            for cont_obj in containers:
                for box in cont_obj["boxes"]:
                    matching_belts = [belt for belt in st.session_state.belts if belt.get("id") == box.get("id")]
                    if matching_belts:
                        belt = matching_belts[0]
                        pos = box["position"]
                        placed_dims = box["placed_dims"]
                        rotation = box.get("rotation_angle", 0)
                        box["rollDiameter"] = belt["rollDiameter"]
                        box["weightPerRoll"] = belt["weightPerRoll"]
                        box["spec"] = belt["spec"]
                        box["length"] = belt["length"]
                        box["core_diameter"] = belt.get("core_diameter", 0.30)
                        box["width_mm"] = belt["width_mm"]
                        box["belt_width"] = belt["belt_width"]
                        box["position"] = pos
                        box["placed_dims"] = placed_dims
                        box["rotation_angle"] = rotation
            st.session_state["containers"] = containers
            st.rerun()

        if st.button("Reload"):
            cont = containerData[container_type].copy()
            cont["max_load"] = custom_max_load
            for belt in st.session_state.belts:
                if belt.get("belt_type") == "chevron":
                    belt["chevron_center"] = center_chevrons

            containers, rejected_belts = pack_belts_into_containers(st.session_state.belts, cont, allow_rotation,
                                                                    forklift_limit)
            st.session_state["containers"] = containers
            st.session_state["needs_reordering"] = False
            st.session_state["last_belts_count"] = -1

            for belt in rejected_belts:
                st.error(f"Belt to heavy for forklift: ({forklift_limit} kg): {belt['spec']}")
            st.rerun()

    else:
        st.info("No belts added yet.")
st.divider()
st.subheader("Container Preview")

for cont_obj in containers:
    container_num = cont_obj["id"]

    st.markdown(
        f"<div style='text-align: center; font-weight: bold; background-color: rgba(24,25,26.7, 0.5); border: 1px solid black; font-size: 18px;'>CONTAINER {container_num}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    col_left, col_right = st.columns([1, 2])
    with col_left:
        if topview_images and isinstance(topview_images, list) and len(topview_images) >= container_num:
            st.image(topview_images[container_num - 1], width=240, caption="DOOR")

    with col_right:
        tab1, tab2 = st.tabs(["Table", "Side-Preview"])
        with tab1:
            table_html = "<table style='width:100%; border-collapse: collapse;'>"
            table_html += (
                "<tr style='border: 1px solid black; background-color: #262730; text-align: center;'>"
                "<th>Color</th>"
                "<th>Nr.</th>"
                "<th>Spec</th>"
                "<th>Length (m)</th>"
                "<th>Width (mm)</th>"
                "<th>Roll Diameter (m)</th>"
                "<th>Weight/roll (kg)</th>"

                "</tr>"
            )
            row_num = 1
            for box in cont_obj["boxes"]:
                color = box.get("color", "#FF0000")
                color_cell = f"<span style='display:inline-block;width:20px;height:20px;background:{color};'></span>"
                table_html += (
                    "<tr style='border: 1px solid black; text-align: center; background-color: #262730;'>"
                    f"<td>{color_cell}</td>"
                    f"<td>{row_num}</td>"
                    f"<td>{box['spec']}</td>"
                    f"<td>{box['length']:.2f}</td>"
                    f"<td>{box['width_mm']:.0f}</td>"
                    f"<td>{box['rollDiameter']:.2f}</td>"
                    f"<td>{box['weightPerRoll']:.2f}</td>"
                    "</tr>"
                )
                row_num += 1
            table_html += "</table>"

            if cont_obj["boxes"]:
                min_z = min(box["position"][2] for box in cont_obj["boxes"])
            else:
                min_z = 0

            placed_area = 0.0
            for box in cont_obj["boxes"]:
                if abs(box["position"][2] - min_z) < 1e-6:
                    if box.get("belt_type") == "chevron":
                        r = box["rollDiameter"] / 2
                        placed_area += math.pi * r * r
                    else:
                        w, h = box.get("placed_dims", (box["belt_width"], box["length"]))
                        placed_area += w * h

            total_area = cont["width"] * cont["length"]
            free_area = total_area - placed_area
            percent = (placed_area / total_area * 100) if total_area else 0

            used_volume = 0.0
            for box in cont_obj["boxes"]:
                w, l = box["placed_dims"]
                h = box["height_3d"]
                used_volume += w * l * h

            total_volume = cont["width"] * cont["length"] * cont["height"]
            free_volume = total_volume - used_volume

            vol_html = f"""
                <div style="background-color:#dddddd; width:100%; border-radius:3px; margin-top:8px;">
                  <div style="background-color:#0fb812; width:{percent:.1f}%; height:10px; border-radius:3px;"></div>
                </div>
                <p style="color:#ffffff; font-size:12px; margin:4px 0 0 0;">
                    Used Volume: {used_volume:.2f} m³ — {free_volume:.2f} m³ free
                </p>
            """

            total_weight = sum(box["weightPerRoll"] for box in cont_obj["boxes"])
            max_weight = cont["max_load"]
            weight_pct = (total_weight / max_weight * 100) if max_weight else 0

            weight_bar_html = f"""
                    <div style="background-color:#dddddd; width:100%; border-radius:3px; margin-top:4px;">
                      <div style="background-color:#eb7e17; width:{weight_pct:.1f}%; height:10px; border-radius:3px;"></div>
                    </div>
                    <p style="color:#ffffff; font-size:12px; margin:4px 0 0 0;">
                        Weight used: {weight_pct:.1f} % ({total_weight:.0f} kg of {max_weight:.0f} kg)
                    </p>
                    """

            st.markdown(table_html, unsafe_allow_html=True)
            st.markdown(vol_html, unsafe_allow_html=True)
            st.markdown(weight_bar_html, unsafe_allow_html=True)

        with tab2:
            if sideview_images and len(sideview_images) >= container_num:
                st.image(sideview_images[container_num - 1], use_container_width=True, caption="RIGHT SIDE")


def get_pdf_image(source, width, max_height=None):

    if isinstance(source, str):
        img = RLImage(source)
    elif isinstance(source, bytes):
        buf = io.BytesIO(source)
        img = RLImage(buf)
    elif hasattr(source, "save"):
        buf = io.BytesIO()
        source.save(buf, format="PNG")
        buf.seek(0)
        img = RLImage(buf)
    else:
        return Paragraph("No picture", getSampleStyleSheet()['BodyText'])

    orig_w, orig_h = img.imageWidth, img.imageHeight
    scale_w = width / orig_w if orig_w else 1
    new_h = orig_h * scale_w
    if max_height is None:
        img.drawWidth = width
        img.drawHeight = new_h
    else:
        if new_h > max_height:
            scale_h = max_height / orig_h if orig_h else 1
            img.drawWidth = orig_w * scale_h
            img.drawHeight = max_height
        else:
            img.drawWidth = width
            img.drawHeight = new_h
    img.hAlign = 'CENTER'
    return img


def belts_to_rejected_df(belts, selected_columns):
    data = []
    for belt in belts:
        filtered = {col: belt.get(col, "") for col in selected_columns}
        data.append(filtered)
    return pd.DataFrame(data)


columns_to_show = ["spec", "length", "belt_width", "rollDiameter", "weightPerRoll", ]
column_names_mapping = {"spec": "Specification", "length": "Length (m)", "belt_width": "Belt width (m)",
                        "rollDiameter": "Roll Diameter (m)", "weightPerRoll": "Weight per Roll (kg)"}


# PDF-Generierung

def create_color_box(color_hex, size=6):
    d = Drawing(size, size)
    rect = Rect(0, 0, size, size, rx=2, ry=2,
                fillColor=colors.HexColor(color_hex),
                strokeColor=colors.HexColor(color_hex))
    d.add(rect)
    return d

def generate_pdf(
    containers,
    topview_images,
    sideview_images,
    order_num=None,
    current_date=None,
    sender=None,
    receiver=None
):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=0,
    )
    styles = getSampleStyleSheet()

    # Styles definieren
    info_style = ParagraphStyle(
        'InfoStyle', parent=styles['Normal'],
        fontSize=8, leading=10, alignment=TA_LEFT, leftIndent=0,
        textColor=colors.HexColor('#4a4a4a')
    )
    title_style = ParagraphStyle(
        'ContainerTitle', parent=styles['Title'],
        fontSize=24, leading=28, alignment=TA_LEFT
    )
    door_style = ParagraphStyle(
        'DoorLabel', parent=styles['Normal'],
        fontSize=10, leading=12, alignment=1
    )

    # Tabellenstile
    table_header_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('ALIGN', (0,0), (-1,0), 'LEFT'),
        ('TOPPADDING', (0,0), (-1,0), 4),
        ('BOTTOMPADDING', (0,0), (-1,0), 3),
    ])

    table_body_style = TableStyle([
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 7),
        ('ALIGN', (0,1), (-1,-1), 'CENTER'),
        ('VALIGN', (0,1), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f7f7f7'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
        ('TOPPADDING', (0,1), (-1,-1), 3),
        ('BOTTOMPADDING', (0,1), (-1,-1), 1),
        ('LEFTPADDING', (0,1), (-1,-1), 6),
        ('RIGHTPADDING', (0,1), (-1,-1), 6),
    ])

    story = []
    page_w, page_h = landscape(A4)
    avail_w = page_w - doc.leftMargin - doc.rightMargin
    avail_h = page_h - doc.topMargin - doc.bottomMargin
    img_w = 135

    for cont in containers:
        num = cont.get('id', 1)

        # Header
        hdr_para = Paragraph(f"LOADING PLAN - CONTAINER {num}", title_style)
        logo = get_pdf_image('static/Vasco Logo+claim fin.jpg', width=150, max_height=150)
        hdr_tbl = Table([[hdr_para, logo]], colWidths=[avail_w*0.67, avail_w*0.3], hAlign='LEFT')
        hdr_tbl.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('ALIGN',(1,0),(1,0),'RIGHT'),
            ('LEFTPADDING',(0,0),(-1,-1),0),
            ('RIGHTPADDING',(0,0),(-1,-1),0),
            ('TOPPADDING',(0,0),(-1,-1),4),
            ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ]))
        story.extend([hdr_tbl, Spacer(1,6)])

        # Info-Zeile
        info_cells = [[
            Paragraph(f"Order-Number: {order_num or 'N/A'}", info_style),
            Paragraph(f"Date: {current_date or 'N/A'}", info_style),
            Paragraph(f"Sender: {sender or 'N/A'}", info_style),
            Paragraph(f"Receiver: {receiver or 'N/A'}", info_style),
        ]]
        first_col_w = avail_w * 0.67
        info_tbl = Table(info_cells, colWidths=[first_col_w/4]*4, hAlign='LEFT')
        info_tbl.setStyle(TableStyle([
            ('ALIGN',(0,0),(-1,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING',(0,0),(-1,-1),0),
            ('RIGHTPADDING',(0,0),(-1,-1),0),
            ('TOPPADDING',(0,0),(-1,-1),2),
            ('BOTTOMPADDING',(0,0),(-1,-1),2),
        ]))
        story.extend([info_tbl, Spacer(1,12)])

        # Ansichten vorbereiten
        tv_flow = Spacer(1,0)
        if topview_images and len(topview_images) >= num:
            tv_img = get_pdf_image(topview_images[num-1], width=img_w, max_height=avail_h*0.58)
            tv_lbl = Paragraph("Door", door_style)
            tv_flow = Table([[tv_img],[tv_lbl]], colWidths=[img_w])
            tv_flow.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER')]))

        sv_flow = Spacer(1,0)
        if sideview_images and len(sideview_images) >= num:
            sv_img = get_pdf_image(sideview_images[num-1], width=img_w, max_height=avail_h*0.2)
            sv_lbl = Paragraph("Door  < >  Back", door_style)
            sv_flow = Table([[sv_img],[sv_lbl]], colWidths=[img_w])
            sv_flow.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER')]))

        left_col = Table([[tv_flow], [sv_flow]], colWidths=[img_w])
        left_col.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (0, 0), 0),
            ('BOTTOMPADDING', (0, 0), (0, 0), 0),
            # Trennlinie unter dem Topview (erste Zeile)
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#cccccc')),
        ]))

        # Gürtel-Tabelle
        headers = ["Color","Nr.","Spec","Length (m)","Width (mm)","Roll Diameter (m)","Weight/roll (kg)"]
        data = [headers] + [[
            create_color_box(b.get('color','#FF0000')),
            i,
            b.get('spec',''),
            f"{b.get('length',0):.2f}",
            f"{b.get('width_mm',0):.0f}",
            f"{b.get('rollDiameter',0):.2f}",
            f"{b.get('weightPerRoll',0):.2f}"
        ] for i,b in enumerate(cont.get('boxes',[]), start=1)]
        box_tbl = Table(data, colWidths=[18 if idx==1 else None for idx in range(len(headers))])
        box_tbl.setStyle(table_header_style)
        box_tbl.setStyle(table_body_style)

        layout = Table([[left_col, box_tbl]], colWidths=[img_w, None])
        layout.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (1, 0), (1, 0), 6 * mm),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(layout)

        # Disclaimer & PageBreak
        story.extend([
            Spacer(1,12),
            Paragraph(
                "Disclaimer: This Loading Plan is a recommendation. Vasco Global is not liable for the final loading of the container.",
                info_style
            ),
            PageBreak()
        ])

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


pdf_data = generate_pdf(containers, topview_images,sideview_images, st.session_state.order_num, st.session_state.current_date,
                        st.session_state.sender, st.session_state.receiver)
st.download_button(label="Download PDF", data=pdf_data, file_name="containers.pdf", mime="application/pdf")

st.divider()
st.subheader("Rejected Belts")
df_rejected = belts_to_rejected_df(st.session_state.get("rejected_belts", []), columns_to_show)
df_rejected = df_rejected.rename(columns=column_names_mapping)
st.dataframe(df_rejected)