import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, Wand2, BookOpen, Zap } from "lucide-react";
import { Button } from "../components/ui/button";

const HERO_BG = "https://images.unsplash.com/photo-1668211834355-2cdf073f2351?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1NzR8MHwxfHNlYXJjaHwzfHxtYW5nYSUyMGFuaW1lJTIwbmVvbiUyMGN5YmVycHVua3xlbnwwfHx8fDE3ODc1ODQxNjV8MA&ixlib=rb-4.1.0&q=85";
const SAMPLE_1 = "https://images.pexels.com/photos/31002131/pexels-photo-31002131.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940";
const SAMPLE_2 = "https://images.unsplash.com/photo-1743951896798-2936f661f939?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2MzR8MHwxfHNlYXJjaHw0fHxza2V0Y2glMjBjaGFyYWN0ZXIlMjBjb25jZXB0JTIwYXJ0fGVufDB8fHx8MTc4NzU4NDE2NXww&ixlib=rb-4.1.0&q=85";
const SAMPLE_3 = "https://images.unsplash.com/photo-1712684063563-dfc94d0bf89f?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2MzR8MHwxfHNlYXJjaHwzfHxza2V0Y2glMjBjaGFyYWN0ZXIlMjBjb25jZXB0JTIwYXJ0fGVufDB8fHx8MTc4NzU4NDE2NXww&ixlib=rb-4.1.0&q=85";

const features = [
  { icon: Sparkles, title: "Hikâye Rehberi", desc: "Yapay zekâ; dünyayı, karakterleri ve 100 bölümlük iskeleti saniyeler içinde yazar." },
  { icon: Wand2, title: "Panel Sanatı", desc: "Nano Banana her panelde tutarlı karakterler çizer." },
  { icon: BookOpen, title: "Düzenlenebilir Balonlar", desc: "Yeniden yazabildiğin, taşıyabildiğin ve stillendirebildiğin SVG diyalog katmanları." },
  { icon: Zap, title: "Talep Üzerine Üretim", desc: "Bölümleri tek tek üret — her adımda canlı ilerleme." },
];

export default function Home() {
  return (
    <div>
      {/* HERO */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 -z-10">
          <img src={HERO_BG} alt="" className="w-full h-full object-cover opacity-40" />
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-slate-950/70 to-[#05050A]" />
        </div>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-16 pb-24 md:pt-28 md:pb-36 relative">
          <div className="max-w-3xl">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.6 }}
              className="inline-flex items-center gap-2 rounded-full border border-violet-500/40 bg-violet-500/10 px-4 py-1.5 mb-6 text-xs tracking-widest uppercase text-violet-200"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
              Yapay Zekâ Manga Stüdyosu
            </motion.div>
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.1 }}
              className="font-display text-6xl sm:text-7xl md:text-8xl leading-[0.9] tracking-wider uppercase"
            >
              Sadece <span className="text-violet-400">senin</span><br />anlatabileceğin hikâyeyi çiz
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.2 }}
              className="mt-6 text-lg text-slate-300 max-w-xl tracking-wide leading-relaxed"
            >
              Tek bir kıvılcım ver. Biz eksiksiz bir hikâye rehberi kurar, tutarlı bir karakter kadrosu oluşturur ve her paneli düzenlenebilir diyalog balonlarıyla mürekkeplendiririz.
            </motion.p>
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.3 }}
              className="mt-10 flex flex-col sm:flex-row gap-4"
            >
              <Link to="/create">
                <Button
                  data-testid="hero-create-btn"
                  className="bg-violet-600 hover:bg-violet-500 text-white font-bold rounded-lg px-8 py-6 text-base tracking-widest uppercase shadow-[0_0_25px_rgba(139,92,246,0.4)] hover:shadow-[0_0_40px_rgba(139,92,246,0.7)]"
                >
                  Oluşturmaya Başla
                </Button>
              </Link>
              <Link to="/explore">
                <Button
                  data-testid="hero-explore-btn"
                  variant="outline"
                  className="border-white/20 bg-transparent hover:bg-white/5 text-slate-100 rounded-lg px-8 py-6 text-base tracking-widest uppercase"
                >
                  Stüdyoyu Keşfet
                </Button>
              </Link>
            </motion.div>
          </div>

          {/* Floating manga sample cards */}
          <div className="hidden lg:block absolute right-4 top-16 w-[380px] h-[520px]">
            {[SAMPLE_1, SAMPLE_2, SAMPLE_3].map((src, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 30, rotate: 0 }}
                animate={{ opacity: 1, y: 0, rotate: [-6, 4, -3][i] }}
                transition={{ duration: 0.8, delay: 0.4 + i * 0.15 }}
                className="absolute rounded-xl overflow-hidden border border-white/10 shadow-2xl"
                style={{
                  top: `${i * 40}px`,
                  left: `${i * 30}px`,
                  width: 260,
                  height: 380,
                  zIndex: 3 - i,
                }}
              >
                <img src={src} alt="" className="w-full h-full object-cover grayscale contrast-125" />
                <div className="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent" />
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-16 md:py-24">
        <div className="mb-12">
          <div className="text-xs tracking-[0.3em] uppercase text-violet-400 mb-3">// Stüdyo Seti</div>
          <h2 className="font-display text-4xl md:text-6xl tracking-wider uppercase">Bir mangakanın ihtiyacı olan her şey.</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {features.map(({ icon: Icon, title, desc }, i) => (
            <motion.div
              key={title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.08 }}
              className="ink-card p-6 hover:border-violet-500/40 hover:-translate-y-1 transition-transform"
            >
              <Icon className="w-8 h-8 text-violet-400 mb-4" />
              <div className="font-display text-2xl tracking-wide mb-2">{title}</div>
              <p className="text-sm text-slate-400 leading-relaxed">{desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* CTA strip */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 pb-24">
        <div className="ink-card p-8 md:p-14 halftone relative overflow-hidden">
          <div className="relative">
            <h3 className="font-display text-4xl md:text-6xl tracking-wider uppercase max-w-2xl">
              İlk mangan <span className="text-violet-400">tek bir istek</span> uzağında.
            </h3>
            <p className="mt-4 text-slate-300 max-w-xl">Anonim, kayıt yok. Dünyanı tasarla, bölüm üret, Keşfet akışında yayınla.</p>
            <Link to="/create">
              <Button
                data-testid="cta-create-btn"
                className="mt-8 bg-violet-600 hover:bg-violet-500 text-white rounded-lg px-8 py-6 tracking-widest uppercase shadow-[0_0_25px_rgba(139,92,246,0.4)]"
              >
                Planımı Oluştur
              </Button>
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
