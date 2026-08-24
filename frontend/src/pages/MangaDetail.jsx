import { useEffect, useState, useRef } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import {
  Loader2, Play, Wand2, Upload, BookOpenText, Sparkles, Users,
  ArrowLeft, Globe, Trash2, Download, Layers, Sliders,
} from "lucide-react";
import { api, fileUrl, API } from "../lib/client";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Slider } from "../components/ui/slider";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "../components/ui/dialog";

const GENRE_TR = {
  "Fantasy": "Fantezi", "Sci-Fi": "Bilim Kurgu", "Slice of Life": "Günlük Yaşam",
  "Action": "Aksiyon", "Romance": "Romantik", "Horror": "Korku",
  "Mystery": "Gizem", "Sports": "Spor", "Isekai": "Isekai",
};
const STYLE_TR = {
  "Manga-inspired": "Manga Esintili",
  "Modern Manhwa": "Modern Manhwa",
  "Retro 90s Ink": "Retro 90'lar Mürekkep",
  "Watercolor Panel": "Sulu Boya Panel",
  "Cyber-Ink Noir": "Siber Mürekkep Noir",
};
const ROLE_TR = {
  "protagonist": "Baş Kahraman",
  "antagonist": "Kötü Karakter",
  "supporting": "Yardımcı",
};

function StatusPill({ status }) {
  const map = {
    outline: { label: "Taslak", cls: "bg-slate-700/60 text-slate-300" },
    generating: { label: "Üretiliyor", cls: "bg-violet-500/20 text-violet-300 animate-pulse" },
    ready: { label: "Hazır", cls: "bg-emerald-500/20 text-emerald-300" },
    error: { label: "Hata", cls: "bg-rose-500/20 text-rose-300" },
  };
  const p = map[status] || map.outline;
  return <span className={`text-[10px] tracking-widest uppercase px-2 py-1 rounded ${p.cls}`}>{p.label}</span>;
}

export default function MangaDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [portraitBusy, setPortraitBusy] = useState({});
  const [chapterJob, setChapterJob] = useState({});
  const [pdfBusy, setPdfBusy] = useState({});
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchFrom, setBatchFrom] = useState([1]);
  const [batchTo, setBatchTo] = useState([5]);
  const [batchRunning, setBatchRunning] = useState(false);
  const [capOpen, setCapOpen] = useState(false);
  const [panelCap, setPanelCap] = useState([8]);
  const streamRefs = useRef({});
  const pollRef = useRef(null);

  const load = async () => {
    try {
      const { data } = await api.get(`/mangas/${id}`);
      setData(data);
      if (data?.manga?.max_panels_per_chapter) {
        setPanelCap([data.manga.max_panels_per_chapter]);
      }
    } catch {
      toast.error("Manga yüklenemedi");
    }
  };

  useEffect(() => {
    (async () => { setLoading(true); await load(); setLoading(false); })();
    return () => {
      Object.values(streamRefs.current).forEach((es) => es?.close());
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line
  }, [id]);

  useEffect(() => {
    const anyGenerating = Object.values(chapterJob).some((j) => j && j.status !== "done" && j.status !== "error");
    if (anyGenerating && !pollRef.current) {
      pollRef.current = setInterval(load, 4000);
    } else if (!anyGenerating && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    // eslint-disable-next-line
  }, [chapterJob]);

  const openStream = (chapterId, jobId) => {
    const es = new EventSource(`${API}/jobs/${jobId}/stream`);
    streamRefs.current[chapterId] = es;
    es.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        setChapterJob((s) => ({ ...s, [chapterId]: d }));
        if (d.status === "done" || d.status === "error") {
          es.close();
          load();
        }
      } catch {}
    };
    es.onerror = () => es.close();
  };

  const generatePortrait = async (charId) => {
    setPortraitBusy((s) => ({ ...s, [charId]: true }));
    try {
      await api.post(`/characters/${charId}/generate-portrait`);
      toast.success("Portre üretildi");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Portre üretilemedi");
    } finally {
      setPortraitBusy((s) => ({ ...s, [charId]: false }));
    }
  };

  const uploadRef = async (charId, file) => {
    const fd = new FormData();
    fd.append("file", file);
    setPortraitBusy((s) => ({ ...s, [charId]: true }));
    try {
      await api.post(`/characters/${charId}/upload-reference`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Referans yüklendi");
      await load();
    } catch {
      toast.error("Yükleme başarısız oldu");
    } finally {
      setPortraitBusy((s) => ({ ...s, [charId]: false }));
    }
  };

  const generateChapter = async (chapterId) => {
    try {
      const { data: job } = await api.post(`/chapters/${chapterId}/generate`);
      setChapterJob((s) => ({ ...s, [chapterId]: { progress: 0, status: "queued" } }));
      openStream(chapterId, job.job_id);
    } catch {
      toast.error("Bölüm üretimi başlatılamadı");
    }
  };

  const runBatch = async () => {
    const from = batchFrom[0];
    const to = batchTo[0];
    if (from > to) { toast.error("Başlangıç değeri bitişten büyük olamaz"); return; }
    const targetChapters = chapters.filter((c) => c.number >= from && c.number <= to);
    if (targetChapters.length === 0) { toast.error("Bu aralıkta bölüm yok"); return; }
    setBatchRunning(true);
    try {
      const { data: res } = await api.post(`/mangas/${id}/chapters/batch-generate`, {
        chapter_ids: targetChapters.map((c) => c.id),
      });
      toast.success(`${res.jobs.length} bölüm sıraya alındı`);
      setBatchOpen(false);
      res.jobs.forEach((j) => {
        setChapterJob((s) => ({ ...s, [j.chapter_id]: { progress: 0, status: "queued" } }));
        openStream(j.chapter_id, j.job_id);
      });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Toplu üretim başarısız oldu");
    } finally {
      setBatchRunning(false);
    }
  };

  const savePanelCap = async () => {
    try {
      await api.patch(`/mangas/${id}/panel-cap`, { max_panels_per_chapter: panelCap[0] });
      toast.success(`Panel limiti ${panelCap[0]} olarak ayarlandı`);
      setCapOpen(false);
      await load();
    } catch {
      toast.error("Kaydedilemedi");
    }
  };

  const publish = async () => {
    try {
      await api.post(`/mangas/${id}/publish`, { is_published: !data.manga.is_published });
      toast.success(data.manga.is_published ? "Yayından kaldırıldı" : "Keşfet akışında yayınlandı");
      load();
    } catch { toast.error("Yayınlanamadı"); }
  };

  const remove = async () => {
    if (!window.confirm("Bu manga kalıcı olarak silinsin mi?")) return;
    await api.delete(`/mangas/${id}`);
    toast.success("Silindi");
    nav("/library");
  };

  const exportPdf = async (chapterId, chapterTitle, chapterNumber) => {
    setPdfBusy((s) => ({ ...s, [chapterId]: true }));
    try {
      const res = await api.get(`/chapters/${chapterId}/export/pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bolum-${String(chapterNumber).padStart(2, "0")}-${chapterTitle.replace(/\s+/g, "_").slice(0, 40)}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast.success("PDF indirildi");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "PDF dışa aktarımı başarısız oldu");
    } finally {
      setPdfBusy((s) => ({ ...s, [chapterId]: false }));
    }
  };

  if (loading || !data) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-24 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-violet-400" />
      </div>
    );
  }

  const { manga, characters, chapters } = data;
  const readyChapters = chapters.filter((c) => c.status === "ready").length;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <Link to="/library" data-testid="back-to-library" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-violet-300 mb-6">
        <ArrowLeft className="w-4 h-4" /> Kütüphaneye Dön
      </Link>

      {/* Header */}
      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-8 mb-12">
        <div className="ink-card overflow-hidden aspect-[2/3] halftone flex items-center justify-center">
          {manga.cover_url ? (
            <img src={fileUrl(manga.cover_url)} alt="kapak" className="w-full h-full object-cover" />
          ) : (
            <div className="text-center p-6">
              <BookOpenText className="w-12 h-12 mx-auto text-violet-500/50 mb-3" />
              <p className="text-slate-400 text-sm">Kapak ilk panel çizildiğinde açılır.</p>
            </div>
          )}
        </div>

        <div>
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <Badge className="bg-violet-500/20 text-violet-200 border-violet-500/40">{GENRE_TR[manga.genre] || manga.genre}</Badge>
            <Badge className="bg-blue-500/20 text-blue-200 border-blue-500/40">{STYLE_TR[manga.art_style] || manga.art_style}</Badge>
            {manga.is_published && <Badge className="bg-emerald-500/20 text-emerald-200 border-emerald-500/40">Yayında</Badge>}
            <Badge className="bg-slate-800 text-slate-300 border-white/10">
              Limit: {manga.max_panels_per_chapter || 8} panel/bölüm
            </Badge>
          </div>
          <h1 className="font-display text-5xl md:text-6xl tracking-widest uppercase">{manga.title}</h1>
          <p className="mt-3 italic text-violet-300 text-lg">{manga.logline}</p>
          <p className="mt-4 text-slate-300 leading-relaxed max-w-3xl">{manga.synopsis}</p>

          <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-4">
            <InfoBlock title="Mekan" value={manga.world?.setting} />
            <InfoBlock title="Güç Sistemi" value={manga.world?.power_system} />
            <InfoBlock title="Atmosfer" value={manga.world?.atmosphere} />
          </div>

          <div className="flex flex-wrap gap-3 mt-6">
            <Dialog open={batchOpen} onOpenChange={setBatchOpen}>
              <DialogTrigger asChild>
                <Button data-testid="batch-open" className="bg-violet-600 hover:bg-violet-500">
                  <Layers className="w-4 h-4 mr-2" /> Toplu Üret
                </Button>
              </DialogTrigger>
              <DialogContent className="bg-slate-950 border-white/10 text-slate-100">
                <DialogHeader>
                  <DialogTitle className="font-display text-2xl tracking-widest uppercase">Bölümleri Sıraya Al</DialogTitle>
                </DialogHeader>
                <div className="space-y-6 py-2">
                  <div>
                    <div className="flex items-baseline justify-between mb-2">
                      <span className="text-xs tracking-widest uppercase text-slate-400">Başlangıç Bölümü</span>
                      <span className="font-mono text-violet-300">{batchFrom[0]}</span>
                    </div>
                    <Slider data-testid="batch-from" value={batchFrom} onValueChange={setBatchFrom} min={1} max={chapters.length} step={1} />
                  </div>
                  <div>
                    <div className="flex items-baseline justify-between mb-2">
                      <span className="text-xs tracking-widest uppercase text-slate-400">Bitiş Bölümü</span>
                      <span className="font-mono text-violet-300">{batchTo[0]}</span>
                    </div>
                    <Slider data-testid="batch-to" value={batchTo} onValueChange={setBatchTo} min={1} max={chapters.length} step={1} />
                  </div>
                  <div className="rounded-lg border border-violet-500/25 bg-violet-500/5 p-3 text-xs text-slate-300">
                    Tahmini {(Math.max(0, batchTo[0] - batchFrom[0] + 1)) * (manga.max_panels_per_chapter || 8)} panel görseli üretilecek. Mevcut bölümler yeniden üretilir.
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setBatchOpen(false)} className="border-white/15">Vazgeç</Button>
                  <Button data-testid="batch-start" onClick={runBatch} disabled={batchRunning} className="bg-violet-600 hover:bg-violet-500">
                    {batchRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sıraya Al"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            <Dialog open={capOpen} onOpenChange={setCapOpen}>
              <DialogTrigger asChild>
                <Button data-testid="cap-open" variant="outline" className="border-white/15 hover:bg-white/5">
                  <Sliders className="w-4 h-4 mr-2" /> Panel Limiti
                </Button>
              </DialogTrigger>
              <DialogContent className="bg-slate-950 border-white/10 text-slate-100">
                <DialogHeader>
                  <DialogTitle className="font-display text-2xl tracking-widest uppercase">Bölüm Başına Panel</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 py-2">
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs tracking-widest uppercase text-slate-400">Limit</span>
                    <span className="font-display text-3xl text-violet-300">{panelCap[0]}</span>
                  </div>
                  <Slider data-testid="cap-slider" value={panelCap} onValueChange={setPanelCap} min={1} max={30} step={1} />
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Daha düşük limit maliyeti azaltır. Her panel bir Nano Banana görsel çağrısıdır.
                  </p>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setCapOpen(false)} className="border-white/15">Vazgeç</Button>
                  <Button data-testid="cap-save" onClick={savePanelCap} className="bg-violet-600 hover:bg-violet-500">Kaydet</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            <Button data-testid="publish-toggle" onClick={publish} variant="outline" className="border-white/15 hover:bg-white/5">
              <Globe className="w-4 h-4 mr-2" /> {manga.is_published ? "Yayından Kaldır" : "Yayınla"}
            </Button>
            <Button data-testid="delete-manga" onClick={remove} variant="outline" className="border-rose-500/40 text-rose-300 hover:bg-rose-500/10">
              <Trash2 className="w-4 h-4 mr-2" /> Sil
            </Button>
          </div>

          <div className="mt-4 text-xs text-slate-500 tracking-widest uppercase">
            {readyChapters}/{chapters.length} bölüm hazır
            {manga.stats ? ` · ${manga.stats.image_calls || 0} görsel üretildi` : ""}
          </div>
        </div>
      </div>

      {/* Characters */}
      <section className="mb-14">
        <div className="flex items-center gap-3 mb-6">
          <Users className="w-5 h-5 text-violet-400" />
          <h2 className="font-display text-3xl tracking-widest uppercase">Kadro</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {characters.map((c) => (
            <div key={c.id} className="ink-card p-5 flex gap-4" data-testid={`character-${c.id}`}>
              <div className="w-24 h-32 rounded-lg overflow-hidden bg-slate-900 border border-white/10 shrink-0 flex items-center justify-center">
                {c.reference_image_url ? (
                  <img src={fileUrl(c.reference_image_url)} alt={c.name} className="w-full h-full object-cover" />
                ) : (
                  <Sparkles className="w-6 h-6 text-slate-600" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-display text-xl tracking-wide">{c.name}</div>
                <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-2">{ROLE_TR[c.role] || c.role}</div>
                <p className="text-xs text-slate-400 line-clamp-3">{c.appearance}</p>
                <div className="flex gap-2 mt-3">
                  <Button
                    data-testid={`generate-portrait-${c.id}`}
                    size="sm"
                    onClick={() => generatePortrait(c.id)}
                    disabled={portraitBusy[c.id]}
                    className="bg-violet-600 hover:bg-violet-500 text-xs"
                  >
                    {portraitBusy[c.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3 mr-1" />}
                    {c.reference_image_url ? "Yeniden Üret" : "Üret"}
                  </Button>
                  <label className="cursor-pointer inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md border border-white/15 hover:bg-white/5">
                    <Upload className="w-3 h-3" /> Yükle
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      data-testid={`upload-ref-${c.id}`}
                      onChange={(e) => e.target.files?.[0] && uploadRef(c.id, e.target.files[0])}
                    />
                  </label>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Chapters */}
      <section>
        <div className="flex items-center gap-3 mb-6">
          <BookOpenText className="w-5 h-5 text-violet-400" />
          <h2 className="font-display text-3xl tracking-widest uppercase">Bölümler</h2>
        </div>
        <div className="space-y-3">
          <AnimatePresence>
            {chapters.map((ch) => {
              const job = chapterJob[ch.id];
              const isGenerating = job && job.status !== "done" && job.status !== "error";
              return (
                <motion.div
                  key={ch.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="ink-card p-5 flex flex-col sm:flex-row sm:items-center gap-4"
                  data-testid={`chapter-row-${ch.number}`}
                >
                  <div className="w-12 h-12 rounded-lg bg-violet-500/15 text-violet-300 flex items-center justify-center font-display text-xl shrink-0">
                    {String(ch.number).padStart(2, "0")}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1">
                      <div className="font-display text-lg tracking-wide truncate">{ch.title}</div>
                      <StatusPill status={ch.status} />
                    </div>
                    <p className="text-xs text-slate-400 line-clamp-2">{ch.summary}</p>
                    {isGenerating && (
                      <div className="mt-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] tracking-widest uppercase text-slate-500">
                            {job.status === "queued" ? "Sırada" : `Çiziliyor · ${job.progress}%`}
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-violet-500 to-blue-400 transition-all"
                            style={{ width: `${job.progress || 0}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2 shrink-0 flex-wrap">
                    {ch.status === "ready" ? (
                      <>
                        <Link to={`/read/${manga.id}/${ch.id}`}>
                          <Button data-testid={`read-chapter-${ch.number}`} className="bg-violet-600 hover:bg-violet-500 text-white">
                            <BookOpenText className="w-4 h-4 mr-2" /> Oku
                          </Button>
                        </Link>
                        <Button
                          data-testid={`export-pdf-${ch.number}`}
                          onClick={() => exportPdf(ch.id, ch.title, ch.number)}
                          disabled={pdfBusy[ch.id]}
                          variant="outline"
                          className="border-white/15 hover:bg-white/5"
                        >
                          {pdfBusy[ch.id] ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Download className="w-4 h-4 mr-2" /> PDF</>}
                        </Button>
                      </>
                    ) : null}
                    <Button
                      data-testid={`generate-chapter-${ch.number}`}
                      onClick={() => generateChapter(ch.id)}
                      disabled={isGenerating}
                      variant="outline"
                      className="border-white/15 hover:bg-white/5"
                    >
                      {isGenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Play className="w-4 h-4 mr-2" /> {ch.status === "ready" ? "Yeniden Üret" : "Üret"}</>}
                    </Button>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      </section>
    </div>
  );
}

function InfoBlock({ title, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/40 p-3">
      <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">{title}</div>
      <div className="text-sm text-slate-200">{value || "—"}</div>
    </div>
  );
}
