import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Loader2, Wand2 } from "lucide-react";
import { api, getClientId, API } from "../lib/client";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Slider } from "../components/ui/slider";

const GENRES = ["Fantasy", "Sci-Fi", "Slice of Life", "Action", "Romance", "Horror", "Mystery", "Sports", "Isekai"];
const ART_STYLES = ["Manga-inspired", "Modern Manhwa", "Retro 90s Ink", "Watercolor Panel", "Cyber-Ink Noir"];
const CREATIVITY = ["conservative", "balanced", "wild"];

export default function Create() {
  const nav = useNavigate();
  const [idea, setIdea] = useState("");
  const [genre, setGenre] = useState("Fantasy");
  const [artStyle, setArtStyle] = useState("Manga-inspired");
  const [chapterCount, setChapterCount] = useState([5]);
  const [creativity, setCreativity] = useState("balanced");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState("");
  const esRef = useRef(null);

  useEffect(() => () => { esRef.current?.close(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (idea.trim().length < 8) {
      toast.error("Idea needs at least 8 characters");
      return;
    }
    setLoading(true);
    setProgress(0);
    setPhase("Sending idea to the studio...");
    try {
      const { data } = await api.post("/mangas", {
        idea,
        genre,
        art_style: artStyle,
        chapter_count: chapterCount[0],
        creativity,
        client_id: getClientId(),
      });
      setPhase("Weaving story bible...");

      // Poll SSE for progress
      const es = new EventSource(`${API}/jobs/${data.job_id}/stream`);
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data);
          if (typeof d.progress === "number") setProgress(d.progress);
          if (d.progress > 60) setPhase("Casting characters and chapters...");
          if (d.status === "done") {
            es.close();
            toast.success("Story plan ready");
            nav(`/manga/${data.manga_id}`);
          } else if (d.status === "error") {
            es.close();
            toast.error(d.error || "Generation failed");
            setLoading(false);
          }
        } catch {}
      };
      es.onerror = () => {
        es.close();
        // Fallback: navigate anyway and let detail page decide
        nav(`/manga/${data.manga_id}`);
      };
    } catch (err) {
      console.error(err);
      toast.error(err?.response?.data?.detail || "Failed to start generation");
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-12">
      <div className="mb-10">
        <div className="text-xs tracking-[0.3em] uppercase text-violet-400 mb-2">// New Project</div>
        <h1 className="font-display text-5xl md:text-6xl tracking-widest uppercase">Forge Your Manga</h1>
        <p className="mt-3 text-slate-400 max-w-xl">One idea in, a full story bible out. You can generate chapters on demand afterwards.</p>
      </div>

      <motion.form
        onSubmit={submit}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="ink-card p-6 md:p-10 space-y-8"
      >
        <div>
          <Label htmlFor="idea" className="uppercase tracking-widest text-xs text-slate-300">The Spark</Label>
          <Textarea
            id="idea"
            data-testid="create-idea-input"
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder="A ronin whose blade whispers the memories of every soul it has cut..."
            rows={4}
            disabled={loading}
            className="mt-2 bg-slate-950/60 border-white/10 focus:border-violet-500 text-base"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <Label className="uppercase tracking-widest text-xs text-slate-300">Genre</Label>
            <Select value={genre} onValueChange={setGenre} disabled={loading}>
              <SelectTrigger data-testid="create-genre-select" className="mt-2 bg-slate-950/60 border-white/10">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-950 border-white/10">
                {GENRES.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="uppercase tracking-widest text-xs text-slate-300">Art Style</Label>
            <Select value={artStyle} onValueChange={setArtStyle} disabled={loading}>
              <SelectTrigger data-testid="create-art-select" className="mt-2 bg-slate-950/60 border-white/10">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-950 border-white/10">
                {ART_STYLES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div>
          <div className="flex items-baseline justify-between mb-2">
            <Label className="uppercase tracking-widest text-xs text-slate-300">Chapters</Label>
            <span className="font-mono text-sm text-violet-300">{chapterCount[0]}</span>
          </div>
          <Slider data-testid="create-chapters-slider" value={chapterCount} onValueChange={setChapterCount} min={1} max={20} step={1} disabled={loading} />
        </div>

        <div>
          <Label className="uppercase tracking-widest text-xs text-slate-300 mb-2 block">Creativity</Label>
          <div className="grid grid-cols-3 gap-3">
            {CREATIVITY.map((c) => (
              <button
                type="button"
                key={c}
                data-testid={`create-creativity-${c}`}
                onClick={() => setCreativity(c)}
                disabled={loading}
                className={`py-3 rounded-lg border tracking-widest uppercase text-xs transition-colors ${
                  creativity === c ? "border-violet-500 bg-violet-500/15 text-violet-200" : "border-white/10 text-slate-400 hover:bg-white/5"
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        {loading && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs tracking-widest uppercase text-slate-400">{phase}</span>
              <span className="font-mono text-sm text-violet-300">{progress}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-violet-500 to-blue-400 transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        <Button
          type="submit"
          data-testid="create-submit-btn"
          disabled={loading}
          className="w-full bg-violet-600 hover:bg-violet-500 text-white font-bold rounded-lg py-6 tracking-widest uppercase shadow-[0_0_25px_rgba(139,92,246,0.4)]"
        >
          {loading ? (
            <><Loader2 className="w-5 h-5 mr-2 animate-spin" /> Weaving story bible...</>
          ) : (
            <><Wand2 className="w-5 h-5 mr-2" /> Generate Manga Plan</>
          )}
        </Button>
      </motion.form>
    </div>
  );
}
