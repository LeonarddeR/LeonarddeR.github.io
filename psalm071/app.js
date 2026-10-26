import createVerovioModule from "https://cdn.jsdelivr.net/npm/verovio@6.3.0/dist/verovio-module.mjs";
import { VerovioToolkit } from "https://cdn.jsdelivr.net/npm/verovio@6.3.0/dist/verovio.mjs";
import { Midi } from "https://cdn.jsdelivr.net/npm/@tonejs/midi@2.0.28/+esm";

const MEI_NS = "http://www.music-encoding.org/ns/mei";

// Keys offered, relative to the E phrygian base file. Each interval is chosen so the
// key signature has the fewest accidentals (D-sharp rather than E-flat phrygian, etc.).
const TOONSOORTEN = [
  { interval: "-M3", name: "C-frygisch", shift: "2 tonen lager" },
  { interval: "-m3", name: "Cis-frygisch", shift: "1½ toon lager" },
  { interval: "-M2", name: "D-frygisch", shift: "1 toon lager, origineel" },
  { interval: "-m2", name: "Dis-frygisch", shift: "½ toon lager" },
  { interval: "", name: "E-frygisch", shift: "" },
  { interval: "m2", name: "F-frygisch", shift: "½ toon hoger" },
  { interval: "M2", name: "Fis-frygisch", shift: "1 toon hoger" },
  { interval: "m3", name: "G-frygisch", shift: "1½ toon hoger" },
  { interval: "M3", name: "Gis-frygisch", shift: "2 tonen hoger" },
];
const BASE_INDEX = 4;

const els = {
  verhogingen: document.getElementById("verhogingen"),
  toonsoort: document.getElementById("toonsoort"),
  play: document.getElementById("play"),
  status: document.getElementById("status"),
  score: document.getElementById("score"),
};

let tk;
let baseMei;
let playback = null;
let highlighted = [];

function scale() {
  return window.matchMedia("(max-width: 600px)").matches ? 30 : 40;
}

function layoutOptions() {
  return { scale: scale(), pageWidth: Math.floor((els.score.clientWidth * 100) / scale()) };
}

function meiForState() {
  const doc = baseMei.cloneNode(true);
  if (!els.verhogingen.checked) {
    for (const accid of [...doc.getElementsByTagNameNS(MEI_NS, "accid")]) {
      if (accid.getAttribute("func") === "edit") accid.remove();
    }
  }
  return new XMLSerializer().serializeToString(doc);
}

function draw() {
  const pages = Array.from({ length: tk.getPageCount() }, (_, i) => tk.renderToSVG(i + 1));
  els.score.innerHTML = pages.join("");
  highlight(highlighted);
}

function load() {
  stop();
  const toonsoort = TOONSOORTEN[els.toonsoort.selectedIndex];
  tk.setOptions({
    ...layoutOptions(),
    transpose: toonsoort.interval,
    // Start every regel on a new system, even when the previous one is short.
    breaks: "smart",
    breaksSmartSb: 0.1,
    adjustPageHeight: true,
    header: "none",
    footer: "none",
  });
  tk.loadData(meiForState());
  draw();
  const description = `${toonsoort.name}, verhogingen ${els.verhogingen.checked ? "aan" : "uit"}`;
  els.score.setAttribute("aria-label", `Bladmuziek van Psalm 71, ${description}`);
  els.status.textContent = `${description}.`;
}

function relayout() {
  tk.setOptions(layoutOptions());
  tk.redoLayout();
  draw();
}

function highlight(ids) {
  for (const el of els.score.querySelectorAll("g.playing")) el.classList.remove("playing");
  for (const id of ids) document.getElementById(id)?.classList.add("playing");
  highlighted = ids;
}

function followPlayback(ids) {
  const el = ids.length && document.getElementById(ids[0]);
  if (!el) return;
  const { top, bottom } = el.getBoundingClientRect();
  if (top < 0 || bottom > window.innerHeight) el.scrollIntoView({ block: "center", behavior: "smooth" });
}

// Principal-like registration: fundamental plus octave, twelfth and fifteenth.
function organWave(ctx) {
  const imag = new Float32Array([0, 1, 0.55, 0.3, 0.32, 0.1, 0.14, 0.04, 0.09]);
  return ctx.createPeriodicWave(new Float32Array(imag.length), imag);
}

function play() {
  const midi = new Midi(Uint8Array.from(atob(tk.renderToMIDI()), (c) => c.charCodeAt(0)));
  const ctx = new AudioContext();
  const wave = organWave(ctx);
  const master = ctx.createGain();
  master.gain.value = 0.12;
  master.connect(ctx.destination);

  const start = ctx.currentTime + 0.1;
  for (const note of midi.tracks.flatMap((track) => track.notes)) {
    const on = start + note.time;
    // Release slightly early so repeated notes are articulated, as on an organ.
    const off = on + Math.max(0.05, note.duration - 0.04);
    const osc = ctx.createOscillator();
    const env = ctx.createGain();
    osc.setPeriodicWave(wave);
    osc.frequency.value = 440 * 2 ** ((note.midi - 69) / 12);
    env.gain.setValueAtTime(0, on);
    env.gain.linearRampToValueAtTime(1, on + 0.02);
    env.gain.setValueAtTime(1, off - 0.02);
    env.gain.linearRampToValueAtTime(0, off);
    osc.connect(env).connect(master);
    osc.start(on);
    osc.stop(off + 0.01);
  }

  const endMs = midi.duration * 1000;
  const tick = () => {
    const ms = (ctx.currentTime - start) * 1000;
    if (ms > endMs) {
      stop("Afspelen klaar.");
      return;
    }
    if (ms >= 0) {
      const { notes = [] } = tk.getElementsAtTime(Math.round(ms));
      if (notes.join() !== highlighted.join()) {
        highlight(notes);
        followPlayback(notes);
      }
    }
    playback.frame = requestAnimationFrame(tick);
  };
  playback = { ctx, frame: requestAnimationFrame(tick) };
  els.play.textContent = "Stoppen";
  els.status.textContent = "Afspelen gestart.";
}

function stop(message = "Afspelen gestopt.") {
  if (!playback) return;
  cancelAnimationFrame(playback.frame);
  playback.ctx.close();
  playback = null;
  highlight([]);
  els.play.textContent = "Afspelen";
  els.status.textContent = message;
}

async function init() {
  for (const [i, { name, shift }] of TOONSOORTEN.entries()) {
    els.toonsoort.add(new Option(shift ? `${name} (${shift})` : name, String(i), i === BASE_INDEX, i === BASE_INDEX));
  }

  const [module, meiText] = await Promise.all([
    createVerovioModule(),
    fetch("psalm071.mei").then((response) => {
      if (!response.ok) throw new Error(`psalm071.mei: ${response.status}`);
      return response.text();
    }),
  ]);
  tk = new VerovioToolkit(module);
  baseMei = new DOMParser().parseFromString(meiText, "application/xml");
  load();

  els.verhogingen.addEventListener("change", load);
  els.toonsoort.addEventListener("change", load);
  els.play.addEventListener("click", () => (playback ? stop() : play()));

  let width = els.score.clientWidth;
  let timer;
  new ResizeObserver(() => {
    if (els.score.clientWidth === width) return;
    width = els.score.clientWidth;
    clearTimeout(timer);
    timer = setTimeout(relayout, 150);
  }).observe(els.score);

  for (const el of [els.verhogingen, els.toonsoort, els.play]) el.disabled = false;
}

init().catch((error) => {
  console.error(error);
  els.status.textContent = "De bladmuziek kon niet worden geladen.";
});
