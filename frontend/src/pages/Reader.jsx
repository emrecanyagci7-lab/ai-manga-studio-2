import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { X, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { api, fileUrl } from "../lib/client";
import { Button } from "../components/ui/button";

function bubbleShapeStyle(type) {
  const base = "border-2 shadow-md";
  if (type === "thought") return `${base} rounded-[45%] border-slate-800 bg-white text-slate-900 italic`;
  if (type === "shout") return `${base} rounded-lg border-slate-900 bg-white text-slate-900 font-bold uppercase`;
  if (type === "narration") return "border border-slate-800 bg-amber-50 text-slate-900 rounded";
  if (type === "sfx") return "text-yellow-300 font-black uppercase drop-shadow-[0_0_8px_rgba(139,92,246,0.7)] bg-transparent border-0 text-2xl";
  if (type === "whisper") return `${base} border-dashed border-slate-500 bg-white/90 text-slate-900 rounded-[35%]`;
  return `${base} rounded-[35%] border-slate-900 bg-white text-slate-900`;
}

function Bubble({ b, panelId, onChange }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(b.text);

  const commit = () => {
    setEditing(false);
    if (text !== b.text) onChange(panelId, { ...b, text });
  };

  return (
    <div
      className="absolute pointer-events-auto"
      style={{
        left: `${b.x * 100}%`,
        top: `${b.y * 100}%`,
        width: `${b.width * 100}%`,
        minHeight: `${b.height * 100}%`,
      }}
      data-testid={`bubble-${b.id}`}
    >
      <div
        onClick={() => setEditing(true)}
        className={`px-3 py-2 text-xs sm:text-sm flex items-center justify-center text-center leading-tight cursor-text ${bubbleShapeStyle(b.type)}`}
        style={{ minHeight: "100%" }}
      >
        {editing ? (
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => { if (e.key === "Enter" && e.metaKey) commit(); }}
            className="w-full bg-transparent outline-none resize-none text-inherit"
            data-testid={`bubble-input-${b.id}`}
          />
        ) : (
          <span>{b.text || "..."}</span>
        )}
      </div>
    </div>
  );
}

export default function Reader() {
  const { mangaId, chapterId } = useParams();
  const nav = useNavigate();
  const [panels, setPanels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [manga, setManga] = useState(null);
  const [chapters, setChapters] = useState([]);
  const debounceRef = useRef({});

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [{ data: p }, { data: m }] = await Promise.all([
          api.get(`/chapters/${chapterId}/panels`),
          api.get(`/mangas/${mangaId}`),
        ]);
        setPanels((p.panels || []).filter((x) => x.image_url));
        setManga(m.manga);
        setChapters(m.chapters);
      } catch {
        toast.error("Okuyucu yüklenemedi");
      } finally {
        setLoading(false);
      }
    })();
  }, [mangaId, chapterId]);

  const updateBubble = (panelId, updated) => {
    setPanels((ps) => ps.map((p) => {
      if (p.id !== panelId) return p;
      const newBubbles = p.bubbles.map((b) => (b.id === updated.id ? updated : b));
      clearTimeout(debounceRef.current[panelId]);
      debounceRef.current[panelId] = setTimeout(() => {
        api.patch(`/panels/${panelId}/bubbles`, { bubbles: newBubbles }).catch(() => {});
      }, 600);
      return { ...p, bubbles: newBubbles };
    }));
  };

  const currentIdx = chapters.findIndex((c) => c.id === chapterId);
  const prevChapter = chapters[currentIdx - 1];
  const nextChapter = chapters[currentIdx + 1];

  return (
    <div className="min-h-screen bg-[#05050A]">
      {/* Reader header */}
      <header className="sticky top-0 z-40 backdrop-blur-2xl bg-slate-950/80 border-b border-white/10">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
          <button
            data-testid="reader-close"
            onClick={() => nav(`/manga/${mangaId}`)}
            className="text-slate-300 hover:text-violet-300 flex items-center gap-2"
          >
            <X className="w-5 h-5" /> <span className="hidden sm:inline text-sm tracking-widest uppercase">Çık</span>
          </button>
          <div className="text-center">
            <div className="font-display text-xl tracking-widest truncate max-w-[60vw]">{manga?.title || "Yükleniyor"}</div>
            <div className="text-[10px] tracking-widest uppercase text-slate-400">
              Bölüm {chapters[currentIdx]?.number} — {chapters[currentIdx]?.title}
            </div>
          </div>
          <div className="flex items-center gap-1">
            {prevChapter && (
              <Link data-testid="reader-prev" to={`/read/${mangaId}/${prevChapter.id}`}>
                <Button size="icon" variant="ghost" className="text-slate-300"><ChevronLeft className="w-5 h-5" /></Button>
              </Link>
            )}
            {nextChapter && (
              <Link data-testid="reader-next" to={`/read/${mangaId}/${nextChapter.id}`}>
                <Button size="icon" variant="ghost" className="text-slate-300"><ChevronRight className="w-5 h-5" /></Button>
              </Link>
            )}
          </div>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center justify-center py-24"><Loader2 className="w-8 h-8 animate-spin text-violet-400" /></div>
      ) : panels.length === 0 ? (
        <div className="max-w-md mx-auto text-center py-24 px-6">
          <p className="text-slate-400">Henüz hazır panel yok. Önce bu bölümü üret.</p>
        </div>
      ) : (
        <div className="max-w-3xl mx-auto py-6 space-y-6 px-3 sm:px-6">
          {panels.map((p, i) => (
            <motion.div
              key={p.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: Math.min(i * 0.03, 0.4) }}
              className="relative rounded-xl overflow-hidden border border-white/10 shadow-2xl bg-slate-900"
              data-testid={`panel-${p.id}`}
            >
              <img src={fileUrl(p.image_url)} alt="" className="w-full block" />
              <div className="absolute inset-0 pointer-events-none">
                {(p.bubbles || []).map((b) => (
                  <Bubble key={b.id} b={b} panelId={p.id} onChange={updateBubble} />
                ))}
              </div>
            </motion.div>
          ))}

          <div className="flex justify-between pt-8 pb-16">
            <div>
              {prevChapter && (
                <Link data-testid="reader-prev-bottom" to={`/read/${mangaId}/${prevChapter.id}`}>
                  <Button variant="outline" className="border-white/15"><ChevronLeft className="w-4 h-4 mr-2" /> Önceki Bölüm</Button>
                </Link>
              )}
            </div>
            <div>
              {nextChapter && (
                <Link data-testid="reader-next-bottom" to={`/read/${mangaId}/${nextChapter.id}`}>
                  <Button className="bg-violet-600 hover:bg-violet-500">Sonraki Bölüm <ChevronRight className="w-4 h-4 ml-2" /></Button>
                </Link>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
