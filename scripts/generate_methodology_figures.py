"""
Script to generate high-resolution diagrams for the IMPARK Methodology chapter.
Outputs both PNG images and LaTeX TikZ source files into the figures/ directory.
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FIGURES_DIR = Path("figures")
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

# Color Palette (Academic / Clean Tech Theme)
BG_COLOR = (255, 255, 255)
TEXT_COLOR = (30, 41, 59)
TEXT_MUTED = (100, 116, 139)
BORDER_COLOR = (148, 163, 184)
ARROW_COLOR = (71, 85, 105)

# Role Colors
BLUE_FILL = (239, 246, 255)
BLUE_BORDER = (59, 130, 246)
GREEN_FILL = (240, 253, 244)
GREEN_BORDER = (34, 197, 94)
PURPLE_FILL = (250, 245, 255)
PURPLE_BORDER = (168, 85, 247)
AMBER_FILL = (254, 252, 232)
AMBER_BORDER = (234, 179, 8)
CYAN_FILL = (236, 254, 255)
CYAN_BORDER = (6, 182, 212)
ROSE_FILL = (255, 241, 242)
ROSE_BORDER = (244, 63, 94)
GRAY_FILL = (248, 250, 252)
GRAY_BORDER = (148, 163, 184)

def get_font(size=14, bold=False):
    try:
        # Windows standard system fonts
        font_path = "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"
        if not os.path.exists(font_path):
            font_path = "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()

FONT_TITLE = get_font(20, bold=True)
FONT_SUBTITLE = get_font(15, bold=True)
FONT_BODY = get_font(13, bold=False)
FONT_BOLD = get_font(13, bold=True)
FONT_SMALL = get_font(11, bold=False)
FONT_TINY = get_font(10, bold=False)

def draw_rounded_rect(draw, box, fill, outline, width=2, radius=10):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)

def draw_arrow(draw, start, end, color=ARROW_COLOR, width=2, arrow_size=8):
    x0, y0 = start
    x1, y1 = end
    draw.line([x0, y0, x1, y1], fill=color, width=width)
    import math
    angle = math.atan2(y1 - y0, x1 - x0)
    # Arrow head
    p1 = (x1 - arrow_size * math.cos(angle - math.pi / 6),
          y1 - arrow_size * math.sin(angle - math.pi / 6))
    p2 = (x1 - arrow_size * math.cos(angle + math.pi / 6),
          y1 - arrow_size * math.sin(angle + math.pi / 6))
    draw.polygon([end, p1, p2], fill=color)

# ==============================================================================
# 1. System Architecture Diagram
# ==============================================================================
def generate_system_architecture():
    width, height = 1400, 850
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title
    draw.text((width // 2, 35), "IMPARK Overall System Architecture", fill=TEXT_COLOR, font=FONT_TITLE, anchor="mm")
    draw.text((width // 2, 65), "Coupled Multi-Agent Orchestration, Heterogeneous Storage, and Local Model Execution", fill=TEXT_MUTED, font=FONT_SUBTITLE, anchor="mm")

    # Layer 1: Client Layer (Top)
    draw_rounded_rect(draw, (80, 110, 1320, 200), GRAY_FILL, GRAY_BORDER, 2)
    draw.text((100, 125), "CLIENT & PRESENTATION TIER (Next.js 15, React 19, TypeScript)", fill=TEXT_COLOR, font=FONT_BOLD)
    
    components = [
        ("Discovery UI", "Scientific name search & autocomplete"),
        ("Leaf Image Upload", "Drag & drop, EXIF transpose"),
        ("Conversation Transcript", "Streaming markdown, citation links"),
        ("Evidence Drawer", "Graph traversal, node provenance & links"),
        ("Agent Activity Trace", "Live subagent routing visualization")
    ]
    box_w = 220
    for i, (title, sub) in enumerate(components):
        x = 110 + i * 242
        draw_rounded_rect(draw, (x, 145, x + box_w, 190), BLUE_FILL, BLUE_BORDER, 1)
        draw.text((x + box_w // 2, 160), title, fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
        draw.text((x + box_w // 2, 177), sub, fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    # Arrow from Client to Gateway
    draw_arrow(draw, (700, 200), (700, 240))
    draw.text((710, 215), "HTTP / JSON REST & Server-Sent Events (SSE)", fill=TEXT_MUTED, font=FONT_TINY)

    # Layer 2: API & Gateway Layer
    draw_rounded_rect(draw, (80, 240, 1320, 330), CYAN_FILL, CYAN_BORDER, 2)
    draw.text((100, 255), "FASTAPI ASYNCHRONOUS BACKEND & RUN MANAGER", fill=TEXT_COLOR, font=FONT_BOLD)
    
    gw_boxes = [
        ("FastAPI Application Root", "Dependency injection, CORS, advisory lease"),
        ("RunManager Service", "Idempotent SHA-256 ops, background tasks"),
        ("Conversation Service", "1-plant scope lock, session mode control"),
        ("SSE Streaming Gateway", "Replayable event log from PostgreSQL")
    ]
    for i, (title, sub) in enumerate(gw_boxes):
        x = 110 + i * 305
        draw_rounded_rect(draw, (x, 275, x + 285, 320), BG_COLOR, CYAN_BORDER, 1)
        draw.text((x + 142, 290), title, fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
        draw.text((x + 142, 307), sub, fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    # Arrow from Gateway to LangGraph
    draw_arrow(draw, (700, 330), (700, 370))

    # Layer 3: Agent Orchestration Layer
    draw_rounded_rect(draw, (80, 370, 1320, 600), PURPLE_FILL, PURPLE_BORDER, 2)
    draw.text((100, 385), "MULTI-AGENT ORCHESTRATION TIER (DeepAgents & LangGraph State Graph)", fill=TEXT_COLOR, font=FONT_BOLD)

    # Outer LangGraph State Graph
    draw_rounded_rect(draw, (110, 415, 430, 580), BG_COLOR, PURPLE_BORDER, 1)
    draw.text((270, 435), "Outer LangGraph State Machine", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw_rounded_rect(draw, (130, 460, 410, 500), AMBER_FILL, AMBER_BORDER, 1)
    draw.text((270, 480), "deep_orchestrator node", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw_rounded_rect(draw, (130, 520, 410, 560), ROSE_FILL, ROSE_BORDER, 1)
    draw.text((270, 535), "clarification node (interrupt)", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((270, 550), "Resumes with same lineage", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    # DeepAgents Main Orchestrator
    draw_rounded_rect(draw, (460, 415, 870, 580), BG_COLOR, BLUE_BORDER, 1)
    draw.text((665, 435), "DeepAgents Main Orchestrator", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((665, 455), "Model: Local Ollama (Gemma 4 / gemma4:e4b)", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")
    
    main_features = [
        "Prompt context synthesis (recent turns + prior facts)",
        "Bounded graph query budget (capped at 3/turn)",
        "Deterministic coverage check via interpret()",
        "Response repair (math cleanup, absence contradiction)",
        "Grounded citation linker & GroundedResponse fallback"
    ]
    for idx, feat in enumerate(main_features):
        draw.text((480, 475 + idx * 20), f"• {feat}", fill=TEXT_COLOR, font=FONT_SMALL)

    # 3 Specialist Subagents
    draw_rounded_rect(draw, (900, 415, 1290, 580), BG_COLOR, GREEN_BORDER, 1)
    draw.text((1095, 435), "Compiled Specialist Subagents", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")

    specialists = [
        ("Text / Entity Subagent", "Tool: resolve_plant_names()", GREEN_FILL, GREEN_BORDER),
        ("Image Understanding Subagent", "Tool: inspect_uploaded_image()", AMBER_FILL, AMBER_BORDER),
        ("Knowledge Graph Subagent", "Tool: retrieve_plant_graph()", CYAN_FILL, CYAN_BORDER)
    ]
    for i, (name, tool, fill, border) in enumerate(specialists):
        y = 460 + i * 40
        draw_rounded_rect(draw, (920, y, 1270, y + 34), fill, border, 1)
        draw.text((935, y + 17), name, fill=TEXT_COLOR, font=FONT_BOLD, anchor="lm")
        draw.text((1255, y + 17), tool, fill=TEXT_MUTED, font=FONT_TINY, anchor="rm")

    # Connecting Arrows inside Tier 3
    draw_arrow(draw, (430, 480), (460, 480))
    draw_arrow(draw, (460, 540), (430, 540))
    draw_arrow(draw, (870, 497), (900, 497))

    # Layer 4: Storage & External Model Execution Tier (Bottom)
    draw_rounded_rect(draw, (80, 640, 1320, 810), GRAY_FILL, GRAY_BORDER, 2)
    draw.text((100, 655), "PERSISTENCE, VECTOR ENGINES, KNOWLEDGE GRAPH & LOCAL INFERENCE", fill=TEXT_COLOR, font=FONT_BOLD)

    dbs = [
        ("PostgreSQL 16 Relational Store", [
            "Sessions, turns & chat messages",
            "search_name (trigram & tsvector GIN)",
            "api_event replay log & binary images",
            "LangGraph AsyncPostgres checkpointer"
        ], BLUE_FILL, BLUE_BORDER),
        ("Qdrant Vector Database", [
            "plant_names_v1 (384-d Cosine)",
            "FastEmbed Multilingual MiniLM",
            "plant_images_v1 (2048-d Cosine)",
            "2,507 indexed leaf vectors"
        ], CYAN_FILL, CYAN_BORDER),
        ("Neo4j 5 Graph Database", [
            "Curated Medicinal Knowledge Graph",
            "8 Node Labels (PlantDetails, Part...)",
            "7 Typed Relations (CONTAINS...)",
            "Code-owned parameterized Cypher"
        ], GREEN_FILL, GREEN_BORDER),
        ("Local Model Runtime (Ollama/CNN)", [
            "Ollama server (gemma4:e4b)",
            "Local fine-tuned Xception CNN",
            "Input shape: 300x400x3, 40 classes",
            "Offloaded execution off event loop"
        ], AMBER_FILL, AMBER_BORDER)
    ]
    for i, (title, items, fill, border) in enumerate(dbs):
        x = 110 + i * 305
        draw_rounded_rect(draw, (x, 675, x + 285, 795), fill, border, 1)
        draw.text((x + 142, 693), title, fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
        for j, item in enumerate(items):
            draw.text((x + 15, 715 + j * 18), f"• {item}", fill=TEXT_MUTED, font=FONT_TINY)

    # Connecting Arrows from Agents to Storage
    draw_arrow(draw, (270, 600), (252, 640)) # LangGraph to Postgres
    draw_arrow(draw, (980, 600), (450, 640)) # Text to Postgres/Qdrant
    draw_arrow(draw, (1100, 600), (1150, 640)) # Image to CNN/Qdrant
    draw_arrow(draw, (1220, 600), (850, 640)) # Graph to Neo4j

    img.save(FIGURES_DIR / "system_architecture.png", "PNG", dpi=(300, 300))
    print("Saved figures/system_architecture.png")

# ==============================================================================
# 2. Methodology Flowchart
# ==============================================================================
def generate_methodology_flowchart():
    width, height = 1000, 1100
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title
    draw.text((width // 2, 35), "IMPARK End-to-End Methodology Flowchart", fill=TEXT_COLOR, font=FONT_TITLE, anchor="mm")
    draw.text((width // 2, 65), "From Multimodal User Query to Grounded Scientific Knowledge Synthesis", fill=TEXT_MUTED, font=FONT_SUBTITLE, anchor="mm")

    steps = [
        ("Step 1: User Request Submission", 
         "User submits leaf photograph or natural language question via Next.js client.",
         BLUE_FILL, BLUE_BORDER),
        ("Step 2: API Intake & Idempotent Run Dispatch", 
         "FastAPI accepts payload, generates SHA-256 digest, allocates RunView, and opens SSE stream.",
         CYAN_FILL, CYAN_BORDER),
        ("Step 3: Session State & Plant Scope Lock Check", 
         "Verifies conversation mode (Discovery vs Conversation). Restricts session to exactly 1 locked plant.",
         PURPLE_FILL, PURPLE_BORDER),
        ("Step 4: DeepAgents Main Orchestration Planning", 
         "Builds turn prompt from recent turns and cited facts. Orchestrator plans delegation to specialist subagents.",
         AMBER_FILL, AMBER_BORDER),
        ("Step 5: Specialist Execution & Multimodal Retrieval", 
         "Text Subagent (Postgres/Qdrant), Image Subagent (Xception CNN/Qdrant), or Graph Subagent (Neo4j Cypher).",
         GREEN_FILL, GREEN_BORDER),
        ("Step 6: Ambiguity Detection & Checkpoint Interrupt", 
         "If botanical identity is ambiguous, Outer LangGraph triggers interrupt() and prompts for clarification.",
         ROSE_FILL, ROSE_BORDER),
        ("Step 7: Bounded Topic Coverage Check", 
         "Deterministic intent analysis via interpret() identifies missed factual topics and executes supplemental queries.",
         AMBER_FILL, AMBER_BORDER),
        ("Step 8: Scientific Response Auditing & Repair", 
         "Filters unsupported efficacy claims, repairs false absence claims, and cleans LaTeX formatting.",
         CYAN_FILL, CYAN_BORDER),
        ("Step 9: Grounded Citation Resolution & Fallback", 
         "Maps evidence UUIDs to numbered brackets [1], attaches links. Dispatches GroundedResponse on timeout.",
         GREEN_FILL, GREEN_BORDER),
        ("Step 10: Persistent State Storage & SSE Stream Delivery", 
         "Persists turn state and checkpoint to PostgreSQL; streams response_delta and completion events to client.",
         BLUE_FILL, BLUE_BORDER)
    ]

    box_w = 780
    box_h = 68
    start_y = 100
    spacing = 98

    for i, (title, desc, fill, border) in enumerate(steps):
        y = start_y + i * spacing
        draw_rounded_rect(draw, (110, y, 110 + box_w, y + box_h), fill, border, 2)
        draw.text((130, y + 20), title, fill=TEXT_COLOR, font=FONT_BOLD)
        draw.text((130, y + 42), desc, fill=TEXT_MUTED, font=FONT_SMALL)
        
        # Step number circle
        draw.ellipse([80 - 16, y + box_h // 2 - 16, 80 + 16, y + box_h // 2 + 16], fill=border, outline=None)
        draw.text((80, y + box_h // 2), str(i + 1), fill=(255, 255, 255), font=FONT_BOLD, anchor="mm")

        # Downward Arrow
        if i < len(steps) - 1:
            draw_arrow(draw, (110 + box_w // 2, y + box_h), (110 + box_w // 2, y + spacing), color=ARROW_COLOR, width=2)

    img.save(FIGURES_DIR / "methodology_flowchart.png", "PNG", dpi=(300, 300))
    print("Saved figures/methodology_flowchart.png")

# ==============================================================================
# 3. Image Classification & Feature Retrieval Workflow
# ==============================================================================
def generate_image_workflow():
    width, height = 1200, 750
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.text((width // 2, 35), "Medicinal Plant Leaf Classification and Vector Fusion Pipeline", fill=TEXT_COLOR, font=FONT_TITLE, anchor="mm")
    draw.text((width // 2, 65), "Coupling Convolutional Feature Extraction with Nearest-Neighbor Density Weighting", fill=TEXT_MUTED, font=FONT_SUBTITLE, anchor="mm")

    # Flowchart boxes
    # Stage 1: Input & Validation
    draw_rounded_rect(draw, (50, 110, 290, 280), BLUE_FILL, BLUE_BORDER, 2)
    draw.text((170, 130), "1. Image Intake & Quality Check", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((70, 160), "• EXIF transposition (ImageOps)", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((70, 185), "• Resolution: min(W,H) >= 64 px", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((70, 210), "• Exposure: mean gray in [12, 245]", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((70, 235), "• Sharpness: Laplacian var >= 3.0", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((70, 260), "• Resize: 400x300, norm [-1, 1]", fill=TEXT_MUTED, font=FONT_TINY)

    draw_arrow(draw, (290, 195), (340, 195))

    # Stage 2: Dual-Output Xception Backbone
    draw_rounded_rect(draw, (340, 110, 640, 280), GREEN_FILL, GREEN_BORDER, 2)
    draw.text((490, 130), "2. Fine-Tuned Xception Model", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((360, 160), "• Backbone: Xception (ImageNet pre-trained)", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((360, 185), "• Input tensor: (1, 300, 400, 3)", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((360, 210), "• GlobalAveragePooling2D: 2,048 dimensions", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((360, 235), "• Dense(256, ReLU) + Dropout(0.40)", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((360, 260), "• Dense(40, Softmax) output layer", fill=TEXT_MUTED, font=FONT_TINY)

    # Split into 2 paths: Softmax vs L2 Vectors
    draw_arrow(draw, (640, 165), (710, 165))
    draw_arrow(draw, (640, 225), (710, 225))

    # Path A: Softmax Probabilities
    draw_rounded_rect(draw, (710, 120, 1150, 190), AMBER_FILL, AMBER_BORDER, 2)
    draw.text((930, 140), "Path A: Direct CNN Probabilities P_CNN(l)", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((930, 165), "40-class softmax distribution over supported botanical species", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    # Path B: Qdrant Cosine Similarity
    draw_rounded_rect(draw, (710, 210, 1150, 340), CYAN_FILL, CYAN_BORDER, 2)
    draw.text((930, 230), "Path B: 2048-d L2-Normalized Vector Retrieval", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((730, 255), "• L2 normalization: v = z / ||z||_2", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((730, 275), "• Query Qdrant collection: plant_images_v1 (2,507 vectors)", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((730, 295), "• Top-80 nearest neighbors ranked by Cosine Similarity", fill=TEXT_MUTED, font=FONT_TINY)
    draw.text((730, 315), "• Exponential density weight: w_l = sum(exp(12 * (s_i - 1)))", fill=TEXT_MUTED, font=FONT_TINY)

    # Fusion Arrow
    draw_arrow(draw, (930, 190), (930, 390))
    draw_arrow(draw, (930, 340), (930, 390))

    # Stage 3: Hybrid Score Fusion
    draw_rounded_rect(draw, (250, 390, 1050, 520), PURPLE_FILL, PURPLE_BORDER, 2)
    draw.text((650, 415), "3. Auditable Hybrid Score Fusion (ranking.py)", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((650, 445), "S_fused(l) = alpha * P_CNN(l) + (1 - alpha) * S_retrieval(l)  [default alpha = 0.75]", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((650, 475), "Prevents out-of-distribution botanical hallucinations while preserving CNN discriminatory power.", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")
    draw.text((650, 500), "If top similarity < 0.60: Triggers clarification request for clearer leaf image.", fill=ROSE_BORDER, font=FONT_SMALL, anchor="mm")

    # Stage 4: Candidate Plant Object
    draw_arrow(draw, (650, 520), (650, 570))
    draw_rounded_rect(draw, (300, 570, 1000, 680), GRAY_FILL, GRAY_BORDER, 2)
    draw.text((650, 595), "4. Candidate Plant Output to DeepAgents Orchestrator", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((650, 625), "CandidatePlant(plant_id, label, confidence, match_method='image_fusion', provenance)", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")
    draw.text((650, 650), "Enters belief state -> Discovery Lock or Checkpoint Clarification Prompt", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    img.save(FIGURES_DIR / "image_workflow.png", "PNG", dpi=(300, 300))
    print("Saved figures/image_workflow.png")

# ==============================================================================
# 4. Text-Based Hybrid Entity Resolution Workflow
# ==============================================================================
def generate_text_workflow():
    width, height = 1200, 800
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.text((width // 2, 35), "Cascaded Hybrid Text Entity Resolution Pipeline", fill=TEXT_COLOR, font=FONT_TITLE, anchor="mm")
    draw.text((width // 2, 65), "Three-Tier Fallback Cascade: Exact Alias -> Lexical Trigram/Fuzzy -> Dense Semantic Vector", fill=TEXT_MUTED, font=FONT_SUBTITLE, anchor="mm")

    # Input Box
    draw_rounded_rect(draw, (400, 100, 800, 170), BLUE_FILL, BLUE_BORDER, 2)
    draw.text((600, 120), "Raw User Text Query / Plant Mention", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((600, 145), "Preprocessing: Lowercase normalization, diacritic strip, stopword filter", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")

    draw_arrow(draw, (600, 170), (600, 210))

    # Stage 1: Exact Match
    draw_rounded_rect(draw, (200, 210, 1000, 310), GREEN_FILL, GREEN_BORDER, 2)
    draw.text((600, 235), "Tier 1: Exact Alias & Catalog Lookup (In-Memory Index)", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((600, 260), "Matches normalized input against 481 PlantAliases and 40 canonical PlantDetails", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")
    draw.text((600, 285), "Decision: Exact match found?  -> Confidence = 0.99 (Single) / 0.79 (Ambiguous) [Return Candidates]", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")

    draw_arrow(draw, (600, 310), (600, 360))
    draw.text((615, 335), "No exact match", fill=ROSE_BORDER, font=FONT_BOLD)

    # Stage 2: Lexical & Fuzzy
    draw_rounded_rect(draw, (200, 360, 1000, 480), AMBER_FILL, AMBER_BORDER, 2)
    draw.text((600, 385), "Tier 2: PostgreSQL FTS + pg_trgm Trigram + RapidFuzz Levenshtein", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((600, 410), "• PostgreSQL GIN tsvector full-text search: min(0.79, 0.50 + 0.25 * score)", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")
    draw.text((600, 435), "• RapidFuzz Levenshtein ratio >= 0.78: min(0.94, 0.65 + 0.30 * ratio)", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")
    draw.text((600, 460), "Decision: Max confidence >= 0.85? -> Return ranked candidates", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")

    draw_arrow(draw, (600, 480), (600, 530))
    draw.text((615, 505), "Max confidence < 0.85 or No hit", fill=ROSE_BORDER, font=FONT_BOLD)

    # Stage 3: Semantic Vector Search
    draw_rounded_rect(draw, (200, 530, 1000, 650), CYAN_FILL, CYAN_BORDER, 2)
    draw.text((600, 555), "Tier 3: Dense Semantic Vector Search (FastEmbed + Qdrant)", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((600, 580), "• Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384-d)", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")
    draw.text((600, 605), "• Qdrant collection: plant_names_v1 (Cosine similarity)", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")
    draw.text((600, 630), "• Filter: cosine_sim >= 0.65 -> Confidence: min(0.79, 0.79 * cosine_sim)", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")

    draw_arrow(draw, (600, 650), (600, 690))

    # Output Box
    draw_rounded_rect(draw, (350, 690, 850, 760), PURPLE_FILL, PURPLE_BORDER, 2)
    draw.text((600, 715), "Ranked Candidate Plants Output", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((600, 740), "Sorted by confidence descending; passed to DeepAgents Orchestrator", fill=TEXT_MUTED, font=FONT_SMALL, anchor="mm")

    img.save(FIGURES_DIR / "text_workflow.png", "PNG", dpi=(300, 300))
    print("Saved figures/text_workflow.png")

# ==============================================================================
# 5. Agent Orchestration & Outer LangGraph Diagram
# ==============================================================================
def generate_agent_orchestration():
    width, height = 1300, 800
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.text((width // 2, 35), "IMPARK Multi-Agent Orchestration Architecture", fill=TEXT_COLOR, font=FONT_TITLE, anchor="mm")
    draw.text((width // 2, 65), "Coordinating DeepAgents Hierarchical Roles with Outer LangGraph State Machine", fill=TEXT_MUTED, font=FONT_SUBTITLE, anchor="mm")

    # Outer LangGraph Container
    draw_rounded_rect(draw, (50, 100, 400, 740), GRAY_FILL, GRAY_BORDER, 2)
    draw.text((225, 125), "Outer LangGraph StateGraph", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((225, 145), "Checkpoint Persistence & Interrupts", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    # LangGraph Nodes
    draw_rounded_rect(draw, (80, 180, 370, 250), BLUE_FILL, BLUE_BORDER, 2)
    draw.text((225, 205), "deep_orchestrator Node", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((225, 225), "Invokes runtime.run(state)", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    draw_rounded_rect(draw, (80, 350, 370, 430), ROSE_FILL, ROSE_BORDER, 2)
    draw.text((225, 380), "clarification Node", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((225, 400), "langgraph.types.interrupt()", fill=ROSE_BORDER, font=FONT_BOLD, anchor="mm")

    draw_rounded_rect(draw, (80, 520, 370, 600), GREEN_FILL, GREEN_BORDER, 2)
    draw.text((225, 550), "AsyncPostgresSaver", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((225, 570), "Durable Postgres Checkpoints", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    # Edges in LangGraph
    draw_arrow(draw, (225, 250), (225, 350))
    draw.text((235, 300), "status == WAITING_USER", fill=TEXT_MUTED, font=FONT_TINY)

    draw_arrow(draw, (180, 350), (180, 250))
    draw.text((120, 300), "Resume input", fill=TEXT_MUTED, font=FONT_TINY)

    draw_arrow(draw, (225, 430), (225, 520))

    # DeepAgents Orchestrator Container
    draw_rounded_rect(draw, (450, 100, 850, 740), BLUE_FILL, BLUE_BORDER, 2)
    draw.text((650, 125), "DeepAgents Main Orchestrator", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
    draw.text((650, 145), "Local Gemma 4 / gemma4:e4b via Ollama", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")

    orch_steps = [
        ("1. Prompt Synthesis", "Resolves follow-ups via effective_question(); bounds context to recent turns + cited facts."),
        ("2. Delegation Planning", "Emits tool calls to text_entity, image_understanding, or knowledge_graph."),
        ("3. Query Budget Control", "Enforces maximum 3 graph calls per turn; caches repeated parameter queries."),
        ("4. Bounded Coverage Check", "Deterministic interpret() detects omitted topics; triggers auto-recovery retrieval."),
        ("5. Quality Repair Loop", "REPAIR_AGENT_PROMPT rewrites false absences & unproven efficacy claims."),
        ("6. Citation Grounding", "Converts UUIDs to bracketed numbers [1]; anchors claims to Neo4j records."),
        ("7. Fallback Safety Net", "GroundedResponseProvider generates deterministic response on model failure.")
    ]
    for i, (title, desc) in enumerate(orch_steps):
        y = 175 + i * 78
        draw_rounded_rect(draw, (470, y, 830, y + 68), BG_COLOR, BLUE_BORDER, 1)
        draw.text((485, y + 18), title, fill=TEXT_COLOR, font=FONT_BOLD)
        draw.text((485, y + 40), desc, fill=TEXT_MUTED, font=FONT_TINY)

    # Specialist Subagents Container
    draw_rounded_rect(draw, (900, 100, 1250, 740), GREEN_FILL, GREEN_BORDER, 2)
    draw.text((1075, 125), "Specialist Subagents & Bound Tools", fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")

    specs = [
        ("Text / Entity Specialist", "resolve_plant_names()", [
            "Hybrid name catalog resolver",
            "PostgreSQL FTS + trigram ops",
            "Qdrant multilingual MiniLM vectors",
            "Returns CandidatePlant list"
        ], CYAN_FILL, CYAN_BORDER),
        ("Image Understanding Specialist", "inspect_uploaded_image()", [
            "Xception CNN feature inference",
            "2048-d image vector retrieval",
            "Auditable score fusion (alpha=0.75)",
            "Resolution & blur quality checks"
        ], AMBER_FILL, AMBER_BORDER),
        ("Knowledge Graph Specialist", "retrieve_plant_graph()", [
            "13 typed allow-listed queries",
            "Neo4j labeled property graph",
            "Parameterized Cypher templates",
            "Evidence records with provenance"
        ], PURPLE_FILL, PURPLE_BORDER)
    ]
    for i, (title, tool, bullets, fill, border) in enumerate(specs):
        y = 170 + i * 190
        draw_rounded_rect(draw, (920, y, 1230, y + 175), fill, border, 1)
        draw.text((1075, y + 20), title, fill=TEXT_COLOR, font=FONT_BOLD, anchor="mm")
        draw.text((1075, y + 40), f"Tool: {tool}", fill=TEXT_MUTED, font=FONT_TINY, anchor="mm")
        for j, b in enumerate(bullets):
            draw.text((935, y + 65 + j * 24), f"• {b}", fill=TEXT_COLOR, font=FONT_TINY)

    # Arrows between Orchestrator and Specialists
    draw_arrow(draw, (830, 240), (920, 240))
    draw_arrow(draw, (830, 430), (920, 430))
    draw_arrow(draw, (830, 620), (920, 620))

    img.save(FIGURES_DIR / "agent_orchestration.png", "PNG", dpi=(300, 300))
    print("Saved figures/agent_orchestration.png")

# ==============================================================================
# 6. Knowledge Graph Schema Diagram
# ==============================================================================
def generate_kg_schema():
    width, height = 1200, 850
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.text((width // 2, 35), "IMPARK Neo4j Knowledge Graph Ontological Schema", fill=TEXT_COLOR, font=FONT_TITLE, anchor="mm")
    draw.text((width // 2, 65), "Verified Graph Topology: 8 Node Labels (3,675 nodes) and 7 Typed Relationships (11,797 edges)", fill=TEXT_MUTED, font=FONT_SUBTITLE, anchor="mm")

    # Define Node positions and properties
    nodes = {
        "PlantDetails": {
            "pos": (120, 200, 320, 330),
            "fill": BLUE_FILL, "border": BLUE_BORDER,
            "title": "PlantDetails (40 nodes)",
            "props": ["plant_name (canonical)", "common_names", "global_status", "regional_status", "taxonomy_id", "iucn_url", "iucn_year"]
        },
        "PlantAlias": {
            "pos": (120, 430, 320, 550),
            "fill": CYAN_FILL, "border": CYAN_BORDER,
            "title": "PlantAlias (481 nodes)",
            "props": ["alias", "normalized_alias", "alias_type", "language", "plant_name"]
        },
        "PlantPart": {
            "pos": (450, 200, 650, 330),
            "fill": GREEN_FILL, "border": GREEN_BORDER,
            "title": "PlantPart (283 nodes)",
            "props": ["plant_name", "plant_part (leaf/root...)", "plant_part_id", "source", "source_url"]
        },
        "TherapeuticUse": {
            "pos": (450, 430, 650, 560),
            "fill": AMBER_FILL, "border": AMBER_BORDER,
            "title": "TherapeuticUse (446 nodes)",
            "props": ["therapeutic_use", "mesh_id", "mesh_category", "mesh_category_name", "source_url"]
        },
        "Phytochemicals": {
            "pos": (780, 200, 980, 340),
            "fill": PURPLE_FILL, "border": PURPLE_BORDER,
            "title": "Phytochemicals (1,772 nodes)",
            "props": ["phytochemical_name", "inchi_key", "smiles", "imppat_id", "chembl_id", "classyfire_class"]
        },
        "Bioactivity": {
            "pos": (780, 430, 980, 570),
            "fill": ROSE_FILL, "border": ROSE_BORDER,
            "title": "Bioactivity (369 nodes)",
            "props": ["bioactivity_id", "standard_type (IC50...)", "standard_value", "standard_units", "normalized_value_nm"]
        },
        "Protein_Target": {
            "pos": (620, 650, 820, 780),
            "fill": BLUE_FILL, "border": BLUE_BORDER,
            "title": "Protein_Target (433 nodes)",
            "props": ["target_name", "uniprot_id", "target_chembl_id", "target_organism", "target_type"]
        },
        "Document": {
            "pos": (940, 650, 1140, 780),
            "fill": GRAY_FILL, "border": GRAY_BORDER,
            "title": "Document (251 nodes)",
            "props": ["document_chembl_id", "document_journal", "document_year", "source_id", "source_url"]
        }
    }

    # Draw nodes
    for key, data in nodes.items():
        x0, y0, x1, y1 = data["pos"]
        draw_rounded_rect(draw, (x0, y0, x1, y1), data["fill"], data["border"], 2)
        draw.text((x0 + 10, y0 + 15), data["title"], fill=TEXT_COLOR, font=FONT_BOLD)
        for i, prop in enumerate(data["props"]):
            draw.text((x0 + 15, y0 + 38 + i * 16), f"• {prop}", fill=TEXT_MUTED, font=FONT_TINY)

    # Relationships & Arrows
    # 1. PlantDetails -> PlantAlias: HAS_ALIAS (481)
    draw_arrow(draw, (220, 330), (220, 430))
    draw.text((230, 380), "HAS_ALIAS (481)", fill=ARROW_COLOR, font=FONT_BOLD)

    # 2. PlantDetails -> PlantPart: HAS_PART (283)
    draw_arrow(draw, (320, 265), (450, 265))
    draw.text((385, 245), "HAS_PART (283)", fill=ARROW_COLOR, font=FONT_BOLD, anchor="mm")

    # 3. PlantPart -> TherapeuticUse: USED_FOR (3,758)
    draw_arrow(draw, (550, 330), (550, 430))
    draw.text((560, 380), "USED_FOR (3,758)", fill=ARROW_COLOR, font=FONT_BOLD)

    # 4. PlantPart -> Phytochemicals: CONTAINS (5,896)
    draw_arrow(draw, (650, 265), (780, 265))
    draw.text((715, 245), "CONTAINS (5,896)", fill=ARROW_COLOR, font=FONT_BOLD, anchor="mm")

    # 5. Phytochemicals -> Bioactivity: HAS_BIOACTIVITY (433)
    draw_arrow(draw, (880, 340), (880, 430))
    draw.text((890, 385), "HAS_BIOACTIVITY (433)", fill=ARROW_COLOR, font=FONT_BOLD)

    # 6. Bioactivity -> Protein_Target: MEASURED_ON (433)
    draw_arrow(draw, (820, 570), (740, 650))
    draw.text((720, 605), "MEASURED_ON (433)", fill=ARROW_COLOR, font=FONT_BOLD)

    # 7. Bioactivity -> Document: REPORTED_IN (413)
    draw_arrow(draw, (940, 570), (1020, 650))
    draw.text((1000, 605), "REPORTED_IN (413)", fill=ARROW_COLOR, font=FONT_BOLD)

    img.save(FIGURES_DIR / "kg_schema.png", "PNG", dpi=(300, 300))
    print("Saved figures/kg_schema.png")

if __name__ == "__main__":
    generate_system_architecture()
    generate_methodology_flowchart()
    generate_image_workflow()
    generate_text_workflow()
    generate_agent_orchestration()
    generate_kg_schema()
    print("All methodology diagrams successfully generated!")
