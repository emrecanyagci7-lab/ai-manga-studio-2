"""Prompt templates for AI Manga Studio pipeline."""

STORY_PLAN_SYSTEM = """You are a master manga writer and world-builder. Create original, engaging manga stories.
You MUST respond with valid JSON only, no prose, no markdown fences.
Never reference existing manga franchises by name. Create fresh, original content."""

STORY_PLAN_USER = """Generate a complete manga story plan based on the user's concept.

Concept: {idea}
Genre: {genre}
Art Style: {art_style}
Number of chapters: {chapter_count}
Tone/Creativity: {creativity}

Return ONLY valid JSON with this exact schema:
{{
  "title": "string - catchy manga title",
  "logline": "string - one sentence hook",
  "synopsis": "string - 3-4 sentence overview",
  "world": {{
    "setting": "string - where/when",
    "power_system": "string - if applicable, else 'None'",
    "atmosphere": "string - mood/vibe"
  }},
  "themes": ["string", "string"],
  "characters": [
    {{
      "name": "string",
      "role": "protagonist|antagonist|supporting",
      "age": "string",
      "appearance": "string - detailed physical description for image generation, 2-3 sentences focusing on hair, eyes, clothing, distinguishing features",
      "personality": "string",
      "backstory": "string - 2-3 sentences"
    }}
  ],
  "chapters": [
    {{"number": 1, "title": "string", "summary": "string - 2-3 sentence plot summary"}}
  ]
}}

Include 3-5 characters. Generate exactly {chapter_count} chapters."""


SCENE_DECOMP_SYSTEM = """You are a manga scene director. Break chapters into cinematic scenes with panel-worthy beats.
Respond with valid JSON only. No prose, no markdown."""

SCENE_DECOMP_USER = """Break this chapter into 3-5 cinematic scenes suitable for manga panels.

Manga: {title}
World: {world_summary}
Story Memory (canonical facts):
{story_memory}

Chapter {chapter_number}: {chapter_title}
Chapter Summary: {chapter_summary}

Characters available: {characters}

Return ONLY valid JSON:
{{
  "scenes": [
    {{
      "order": 1,
      "location": "string",
      "time_of_day": "string",
      "action_summary": "string - what happens",
      "characters_present": ["character name"],
      "panels": [
        {{
          "order": 1,
          "camera": "wide|medium|close-up|extreme close-up|over-shoulder|dutch angle",
          "description": "string - detailed visual description for image generation",
          "characters_in_panel": ["character name"],
          "expression_and_pose": "string",
          "background": "string",
          "dialogue": [
            {{"character": "name or 'NARRATOR'", "text": "string", "type": "speech|thought|shout|whisper|narration|sfx"}}
          ]
        }}
      ]
    }}
  ]
}}

Rules:
- 2-4 panels per scene
- Not every panel needs dialogue; sometimes visual-only panels work best
- Use SFX sparingly for impact
- Keep dialogue punchy and character-consistent"""


IMAGE_PROMPT_TEMPLATE = """{art_style} style manga panel, black and white ink with dynamic screentones.

Scene: {panel_description}
Camera: {camera}
Characters: {characters_desc}
Expression/Pose: {expression_and_pose}
Background: {background}

Style guide: high-contrast manga art, bold ink lines, dramatic shading, screentone dot patterns, expressive character faces. NO text bubbles, NO dialogue text in image, NO written words. Clean composition ready for dialogue overlay."""


CHARACTER_PORTRAIT_PROMPT = """{art_style} style character portrait for manga reference sheet.

Character: {name}
Description: {appearance}
Personality hint: {personality}

Full body pose, neutral expression, front-facing, clean white/gray background, black and white manga ink art with screentones, high detail on face and clothing, model sheet quality. NO text, NO watermarks, NO logos."""
