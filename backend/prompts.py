"""AI Manga Studio prompt şablonları — Türkçe içerik + İngilizce görsel promptları."""

STORY_PLAN_SYSTEM = """Sen usta bir manga yazarısın ve dünya kurucususun. Özgün, sürükleyici manga hikayeleri üret.
Yanıtın YALNIZCA geçerli JSON olmalı — düz metin yok, markdown fence yok, açıklama yok.
Var olan manga franchise isimlerine referans verme. Her zaman taze ve özgün içerik üret.

ÖNEMLİ DİL KURALI:
- Tüm başlıklar, karakter isimleri, sinopsisi, dünya açıklaması, güç sistemi, karakter kişilik ve geçmişleri, bölüm başlıkları ve özetleri MUTLAKA Türkçe olsun.
- Sadece JSON anahtar adları (schema key'leri) İngilizce kalsın. Değerler Türkçe olacak.
- Karakter görünüş açıklaması ('appearance' alanı) İngilizce olsun — çünkü görsel üretim modelinde kullanılacak."""

STORY_PLAN_USER = """Kullanıcının fikrine dayanarak eksiksiz bir manga hikaye planı üret.

Fikir: {idea}
Tür: {genre}
Sanat Stili: {art_style}
Bölüm Sayısı: {chapter_count}
Ton/Yaratıcılık: {creativity}

YALNIZCA bu schema'daki geçerli JSON'u döndür:
{{
  "title": "string - çarpıcı Türkçe manga başlığı",
  "logline": "string - tek cümlelik Türkçe tanıtım",
  "synopsis": "string - 3-4 cümlelik Türkçe genel bakış",
  "world": {{
    "setting": "string - Türkçe: nerede/ne zaman",
    "power_system": "string - Türkçe: varsa güç sistemi, yoksa 'Yok'",
    "atmosphere": "string - Türkçe: atmosfer/his"
  }},
  "themes": ["string Türkçe", "string Türkçe"],
  "characters": [
    {{
      "name": "string - Türkçe karakter adı",
      "role": "protagonist|antagonist|supporting",
      "age": "string - Türkçe (örn '17 yaşında')",
      "appearance": "string - İNGİLİZCE detaylı fiziksel açıklama, görsel üretimi için: saç, göz, kıyafet, ayırt edici özellikler (2-3 cümle)",
      "personality": "string - Türkçe kişilik",
      "backstory": "string - Türkçe 2-3 cümle geçmiş"
    }}
  ],
  "chapters": [
    {{"number": 1, "title": "string - Türkçe bölüm başlığı", "summary": "string - Türkçe 2-3 cümle özet"}}
  ]
}}

Tam olarak 3-5 karakter dahil et. Tam olarak {chapter_count} bölüm üret."""


SCENE_DECOMP_SYSTEM = """Sen bir manga sahne yönetmenisin. Bölümleri manga paneline uygun sinematik sahnelere böl.
Yanıtın YALNIZCA geçerli JSON olmalı — düz metin yok, markdown yok.

ÖNEMLİ DİL KURALI:
- Tüm diyaloglar ('dialogue' alanındaki 'text'), narration, iç düşünce, SFX metinleri Türkçe olsun.
- Panel görsel açıklaması ('description'), 'expression_and_pose', 'background', 'camera' değerleri İngilizce olsun — bunlar görsel üretim modeline gidecek.
- Lokasyon isimleri, karakter isimleri, sahne özeti Türkçe kalabilir."""

SCENE_DECOMP_USER = """Bu bölümü manga panellerine uygun 3-5 sinematik sahneye böl.

Manga: {title}
Dünya: {world_summary}
Hikaye Belleği (kanonik gerçekler):
{story_memory}

Bölüm {chapter_number}: {chapter_title}
Bölüm Özeti: {chapter_summary}

Mevcut karakterler: {characters}

YALNIZCA bu geçerli JSON'u döndür:
{{
  "scenes": [
    {{
      "order": 1,
      "location": "string - Türkçe mekan",
      "time_of_day": "string - Türkçe zaman",
      "action_summary": "string - Türkçe ne olduğu",
      "characters_present": ["karakter adı"],
      "panels": [
        {{
          "order": 1,
          "camera": "wide|medium|close-up|extreme close-up|over-shoulder|dutch angle",
          "description": "string - İNGİLİZCE detaylı görsel açıklama (görsel üretimi için)",
          "characters_in_panel": ["karakter adı"],
          "expression_and_pose": "string - İNGİLİZCE ifade ve poz",
          "background": "string - İNGİLİZCE arkaplan",
          "dialogue": [
            {{"character": "karakter adı veya 'ANLATICI'", "text": "TÜRKÇE diyalog", "type": "speech|thought|shout|whisper|narration|sfx"}}
          ]
        }}
      ]
    }}
  ]
}}

Kurallar:
- Sahne başına 2-4 panel
- Her panelde diyalog olmak zorunda değil; bazen sadece görsel panel daha iyi çalışır
- SFX'i etkili anlar için tasarruflu kullan (kısa Türkçe SFX: PATLAMA, ÇAT, VJIINN)
- Diyaloglar kısa, karakter-tutarlı ve TÜRKÇE olsun"""


IMAGE_PROMPT_TEMPLATE = """{art_style} style manga panel, black and white ink with dynamic screentones.

Scene: {panel_description}
Camera: {camera}
Characters: {characters_desc}
Expression/Pose: {expression_and_pose}
Background: {background}

Style guide: high-contrast manga art, bold ink lines, dramatic shading, screentone dot patterns, expressive character faces. NO text bubbles, NO dialogue text in image, NO written words, NO speech balloons. Clean composition ready for dialogue overlay."""


CHARACTER_PORTRAIT_PROMPT = """{art_style} style character portrait for manga reference sheet.

Character: {name}
Description: {appearance}
Personality hint: {personality}

Full body pose, neutral expression, front-facing, clean white/gray background, black and white manga ink art with screentones, high detail on face and clothing, model sheet quality. NO text, NO watermarks, NO logos, NO speech bubbles."""
