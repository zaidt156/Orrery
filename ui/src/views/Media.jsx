import { useState } from "react";
import { PlayIcon } from "../components/icons.jsx";
import PageHero from "../components/PageHero.jsx";

const TABS = ["Image", "Video", "Library"];

export default function Media() {
  const [seg, setSeg] = useState("Image");
  return (
    <section className="view">
      <div className="media-wrap">
        <div className="media-preview-note" role="status">
          Preview only — this screen is a mockup of a feature that has not been built.
        </div>
        <PageHero
          compact
          title="Media Hub"
          subtitle="A design preview of the planned media workspace. Nothing here generates or saves anything yet — Chat can already create image, audio, and video files today."
        />
        <div className="media-toolbar">
          <div className="seg">
            {TABS.map((t) => (
              <button key={t} className={seg === t ? "on" : ""} onClick={() => setSeg(t)}>{t}</button>
            ))}
          </div>
          <span className="pill model-pill"><b>your image model</b> ⌄</span>
          <div className="grow" />
          <span className="pill"><span className="sdot" style={{ width: "6px", height: "6px", background: "var(--green)" }} />your keys</span>
        </div>

        <div className="media-body">
          <div className="create-panel">
            <div className="field"><label>Prompt</label><textarea rows={4} readOnly value="A bioluminescent observatory under a sweeping aurora, long exposure, ultra-detailed" /></div>
            <div className="field"><label>Negative</label><div className="input mono" style={{ fontSize: "11px", color: "var(--muted)" }}>blurry, watermark, text</div></div>
            <div className="field"><label>Aspect</label>
              <div className="aspect-row"><span className="aspect on">1:1</span><span className="aspect">16:9</span><span className="aspect">9:16</span><span className="aspect">3:2</span></div>
            </div>
            <div className="field"><label>Count &amp; seed</label>
              <div className="aspect-row"><span className="aspect">×4</span><span className="aspect">seed 7741</span><span className="aspect">steps 30</span></div>
            </div>
            <div className="field"><label>Reference (img→img / img→video)</label><div className="refdrop">drop an image, or pin one from Chat</div></div>
            <button className="gen-btn" disabled title="Media generation is not built yet.">✦ Generate</button>
            <div className="gen-cost">not connected yet — see the roadmap for the generation adapters</div>
          </div>

          <div className="gallery-wrap">
            <div className="gallery">
              <div className="tile wide">
                <div className="art" style={{ background: "radial-gradient(120% 100% at 20% 0%,#27407a,#0b1020 60%),radial-gradient(80% 80% at 80% 90%,#7a5acf55,transparent)" }} />
                <span className="vbadge">▶ video · 6s</span>
                <div className="play"><PlayIcon /></div>
                <div className="cap">aurora timelapse over the observatory — image→video</div>
                <div className="acts"><span>Remix</span><span>♥</span></div>
              </div>
              <div className="tile">
                <div className="art" style={{ background: "radial-gradient(100% 100% at 30% 20%,#2e6f8f,#0b1020 70%)" }} />
                <span className="pinmark">★</span>
                <div className="cap">observatory · aurora · v1</div>
              </div>
              <div className="tile">
                <div className="art" style={{ background: "radial-gradient(100% 100% at 70% 30%,#8f6b2e,#0b1020 70%)" }} />
                <div className="cap">warmer palette · v2</div>
                <div className="acts"><span>Pin</span><span>♥</span></div>
              </div>
              <div className="tile">
                <div className="art" style={{ background: "radial-gradient(100% 100% at 40% 60%,#5b3a8f,#0b1020 70%)" }} />
                <div className="cap">violet variant · v3</div>
                <div className="acts"><span>Pin</span><span>♥</span></div>
              </div>
              <div className="tile">
                <div className="art" style={{ background: "radial-gradient(100% 100% at 60% 40%,#2e8f6b,#0b1020 70%)" }} />
                <div className="cap">teal variant · v4</div>
                <div className="acts"><span>Pin</span><span>♥</span></div>
              </div>
              <div className="tile add" style={{ borderStyle: "dashed", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--faint)", fontSize: "11px", aspectRatio: "1" }}>history →</div>
            </div>
          </div>
        </div>

        <div className="media-foot">Planned: prompts and settings saved to your database, files in a local media library, assets reusable from Chat and Automations. None of it is implemented — the tiles below are placeholder art.</div>
      </div>
    </section>
  );
}
