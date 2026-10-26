"""
Build psalm071/psalm071.mei from the MuseScore score of Psalm 71.

Pipeline: .mscz → MuseScore 4 CLI → MusicXML → Verovio → MEI → repair + annotate
→ transpose from D to E phrygian → MEI.

Usage:
    uv run --with verovio==6.3.0 tools/build_psalm071.py <071.mscz> <out.mei>
"""

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import verovio

MUSESCORE_EXE = Path(r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe")

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"mei": MEI_NS}

# Soprano notes (staff 1, layer 1) that carry a "toevallige verhoging":
# regel 4, 7th note and regel 5, 6th note. Both are f-sharp in the D phrygian source.
VERHOGING_MEASURES = (31, 40)

# Last measure of regels 1-5; a system break follows each of them.
REGEL_ENDS = (10, 17, 24, 34, 42)

# lilypond-export wrote the held soprano d' of regel 6 as untied whole notes in
# measures 49, 51, 53 and 55 (with empty measures in between). These measures are
# rebuilt as tied half notes; measure 57 keeps the final whole-note chord.
BROKEN_ENDING = range(49, 57)

# \tempo 2 = 90 in 071.ly
TEMPO_QPM = 180

# Transpositions offered on the page, relative to E phrygian.
TRANSPOSITIONS = {-4: "-M3", -3: "-m3", -2: "-M2", -1: "-m2", 0: "", 1: "m2", 2: "M2", 3: "m3", 4: "M3"}


def q(tag: str) -> str:
    return f"{{{MEI_NS}}}{tag}"


def export_musicxml(mscz: Path, out_dir: Path) -> Path:
    xml_path = out_dir / f"{mscz.stem}.musicxml"
    subprocess.run([str(MUSESCORE_EXE), "-o", str(xml_path), str(mscz)], check=True, capture_output=True)
    return xml_path


def load(tk: verovio.toolkit, data: str) -> None:
    if not tk.loadData(data):
        raise RuntimeError(f"Verovio could not load the score:\n{tk.getLog()}")


def measures_by_number(root: ET.Element) -> dict[int, ET.Element]:
    return {int(m.get("n")): m for m in root.iterfind(".//mei:measure", NS)}


def layer(measure: ET.Element, staff: int, layer_n: int) -> ET.Element:
    found = measure.find(f"mei:staff[@n='{staff}']/mei:layer[@n='{layer_n}']", NS)
    if found is None:
        raise RuntimeError(f"Measure {measure.get('n')} has no staff {staff} layer {layer_n}")
    return found


def repair_ending(measures: dict[int, ET.Element]) -> None:
    soprano_notes = []
    for n in BROKEN_ENDING:
        measure = measures[n]
        measure.attrib.pop("metcon", None)
        for lv in measure.findall("mei:lv", NS):
            measure.remove(lv)
        for staff_layer in measure.iterfind("mei:staff/mei:layer", NS):
            for space in staff_layer.findall("mei:space", NS):
                staff_layer.remove(space)
        soprano = layer(measure, 1, 1)
        for child in list(soprano):
            soprano.remove(child)
        note = ET.SubElement(
            soprano,
            q("note"),
            {XML_ID: f"ending-d-{n}", "dur.ppq": "2", "dur": "2", "oct": "4", "pname": "d", "stem.dir": "up"},
        )
        soprano_notes.append((measure, note))

    final_note = layer(measures[BROKEN_ENDING.stop], 1, 1).find("mei:note", NS)
    for lv in measures[BROKEN_ENDING.stop].findall("mei:lv", NS):
        measures[BROKEN_ENDING.stop].remove(lv)
    targets = [note for _, note in soprano_notes[1:]] + [final_note]
    for (measure, start), end in zip(soprano_notes, targets):
        ET.SubElement(
            measure,
            q("tie"),
            {XML_ID: f"ending-tie-{measure.get('n')}", "startid": f"#{start.get(XML_ID)}", "endid": f"#{end.get(XML_ID)}"},
        )

    for n in BROKEN_ENDING:
        for staff_layer in measures[n].iterfind("mei:staff/mei:layer", NS):
            length = sum(int(e.get("dur.ppq", 0)) for e in staff_layer)
            if length != 2:
                raise RuntimeError(f"Measure {n} still has a layer of {length} quarters after repair")


def mark_verhogingen(measures: dict[int, ET.Element]) -> None:
    for n in VERHOGING_MEASURES:
        note = layer(measures[n], 1, 1).find("mei:note", NS)
        accid = note.find("mei:accid", NS) if note is not None else None
        if note is None or note.get("pname") != "f" or accid is None or accid.get("accid") != "s":
            raise RuntimeError(f"Expected f-sharp in the soprano of measure {n}")
        note.attrib.pop("accid.ges", None)
        accid.attrib.pop("accid.ges", None)
        accid.set("func", "edit")
        accid.set("place", "above")


def add_layout(root: ET.Element, measures: dict[int, ET.Element]) -> None:
    # MuseScore exports its own line layout; replace it with one system per regel.
    for section in root.iterfind(".//mei:section", NS):
        for sb in section.findall("mei:sb", NS):
            section.remove(sb)
    for n in REGEL_ENDS:
        measure = measures[n]
        section = root.find(f".//mei:section/mei:measure[@n='{n}']/..", NS)
        section.insert(list(section).index(measure) + 1, ET.Element(q("sb"), {XML_ID: f"regel-break-{n}"}))
    root.find(".//mei:scoreDef", NS).set("midi.bpm", str(TEMPO_QPM))
    title = root.find(".//mei:titleStmt/mei:title", NS)
    title.text = "Psalm 71"


def edit_mei(mei: str) -> str:
    ET.register_namespace("", MEI_NS)
    root = ET.fromstring(mei)
    measures = measures_by_number(root)
    repair_ending(measures)
    mark_verhogingen(measures)
    add_layout(root, measures)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def strip_verhogingen(mei: str) -> str:
    """Same operation as the page: drop every editorial accidental."""
    root = ET.fromstring(mei)
    for note in root.iterfind(".//mei:note", NS):
        for accid in note.findall("mei:accid[@func='edit']", NS):
            note.remove(accid)
    return ET.tostring(root, encoding="unicode")


def check(mei: str) -> None:
    root = ET.fromstring(mei)
    targets = [n.get(XML_ID) for n in root.iterfind(".//mei:note", NS) if n.find("mei:accid[@func='edit']", NS) is not None]
    if len(targets) != len(VERHOGING_MEASURES):
        raise RuntimeError(f"Expected {len(VERHOGING_MEASURES)} verhogingen, found {len(targets)}")
    variants = {True: mei, False: strip_verhogingen(mei)}
    for semitones, interval in TRANSPOSITIONS.items():
        for shown, data in variants.items():
            tk = verovio.toolkit()
            tk.setOptions({"transpose": interval})
            load(tk, data)
            tk.renderToMIDI()
            expected = 68 + semitones if shown else 67 + semitones
            for note_id in targets:
                pitch = tk.getMIDIValuesForElement(note_id)["pitch"]
                if pitch != expected:
                    raise RuntimeError(f"{interval or 'P1'}, verhogingen {shown}: {note_id} is {pitch}, expected {expected}")
            timemap = tk.renderToTimemap({"includeMeasures": True})
            measure_count = sum(1 for e in timemap if "measureOn" in e)
            # 56 measures of 2/4 + a final 4/4 measure = 116 quarters at 180 qpm.
            duration_ms = timemap[-1]["tstamp"]
            if measure_count != 57 or abs(duration_ms - 116 * 60000 / TEMPO_QPM) > 1:
                raise RuntimeError(f"{interval or 'P1'}: {measure_count} measures, {duration_ms} ms")
    print(f"Checked {len(TRANSPOSITIONS)} transpositions with and without verhogingen")


def main(mscz: Path, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = export_musicxml(mscz, Path(tmp))
        tk = verovio.toolkit()
        # Only encoded breaks, so getMEI() does not write Verovio's own line breaks into the data.
        tk.setOptions({"xmlIdSeed": 71, "breaks": "encoded"})
        if not tk.loadFile(str(xml_path)):
            raise RuntimeError(f"Verovio could not load {xml_path}:\n{tk.getLog()}")
    edited = edit_mei(tk.getMEI())

    tk = verovio.toolkit()
    tk.setOptions({"transpose": "M2", "breaks": "encoded"})
    load(tk, edited)
    result = tk.getMEI()
    check(result)
    out.write_text(result, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
