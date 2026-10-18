# Frontend Design & UX Specification

## Project

**Multi-Agent Intelligent Systems for Indian Medicinal Plant Classification and Knowledge Retrieval**

## Purpose of this document

Use this file as the source of truth for the **frontend design and user experience** of the MVP demo. Build a polished, responsive, modern web interface with the familiar usability of leading AI chat products, but give it its own botanical-research identity.

The existing project documentation already defines the agents, orchestration, state, backend, and contracts. **Do not redesign those systems in this task.** First inspect the existing frontend, package scripts, component library, API contracts, and repository conventions. Then implement the UI in the stack and patterns already present. Do not replace working project infrastructure merely to match this document.

---

## 1. Product experience

The product helps a user establish the identity of an Indian medicinal plant and then investigate it through a persistent, evidence-aware conversational interface.

The experience has two visible modes:

1. **Plant discovery** — every newly created session starts here. The user searches by plant name, describes a plant or what they know about it, uploads an image, or combines text and an image. If the identity is unclear, the UI presents candidate plants and asks the user to choose or clarify.
2. **Conversation** — this becomes available only after the plant context is established. Follow-up questions remain grounded in that active plant context until the user starts a new exploration or introduces another plant that needs resolution.

This distinction is a core UX requirement: **a new session must not open as an unrestricted “Ask anything” chatbot.** The discovery screen should feel like a considered plant-identification and knowledge-exploration entry point. After confirmation, the user should transition naturally into a full chat experience.

### Primary UX goals

- Feel calm, premium, contemporary, and carefully art-directed—not like a generic admin dashboard or a school project template.
- Make the first action obvious without making the user read instructions.
- Keep discovery flexible: name search, natural-language description, image upload, and text + image must all be easy to find.
- Make uncertainty actionable through understandable candidate choices and clarification controls.
- Make the established plant visible throughout the conversation.
- Make ongoing investigation feel responsive with streaming answers and restrained progress feedback.
- Prioritize readable scientific information, evidence provenance, and clear distinctions between established facts and uncertain or traditional claims.
- Work well on desktop, tablet, and mobile.

---

## 2. Art direction and visual identity

Create an original interface informed by the **clarity and interaction quality** of modern AI chat products such as ChatGPT, Claude, and Gemini. Do not copy their exact layouts, branding, icons, or visual assets. This product should feel like a focused botanical knowledge workspace.

### Visual direction

- **Botanical, editorial, minimal.** Use restrained forest/leaf greens, warm neutral surfaces, strong type hierarchy, subtle separators, and generous whitespace.
- **Dark mode is the initial/default theme**, with a complete, deliberate light theme if the existing application supports or can reasonably support theme switching.
- Prefer flat, layered surfaces and thin borders. Avoid glassmorphism, frosted-glass panels, excessive blur, heavy drop shadows, and a dashboard made from many small cards.
- Avoid purple as a primary accent, neon green, overdone gradients, excessive animation, decorative blobs, and generic AI sparkle imagery.
- Use botanical imagery only when it adds value and is available from a trustworthy existing asset/API. Do not fabricate specimen photos or show unrelated stock plant images as if they identify the user's upload.
- Use Lucide or the project's existing icon library consistently. Keep icons simple and mostly monochrome; use emoji only when already established by the project.

### Suggested design tokens

Adapt these values to the current CSS/theme system rather than introducing a second styling system.

#### Dark theme (default)

- App background: `#111411`
- Primary surface: `#171B17`
- Elevated surface: `#1D231D`
- Hover surface: `#242B24`
- Primary text: `#E9EEE8`
- Secondary text: `#A4AEA3`
- Muted text: `#788477`
- Border: `#2B332B`
- Subtle border: `#222922`
- Botanical accent: `#91C995`
- Strong accent / primary action: `#75B980`
- Accent foreground: `#102014`
- Focus ring: `#A7D9AB`
- Destructive/error: `#E28C83`
- Warning/needs-attention: `#E4BE78`

#### Light theme (if included)

- App background: `#F7F8F4`
- Primary surface: `#FFFFFF`
- Elevated surface: `#F0F3EC`
- Hover surface: `#E8EDE4`
- Primary text: `#202820`
- Secondary text: `#606C60`
- Muted text: `#7C877A`
- Border: `#DDE4D9`
- Botanical accent: `#397A48`
- Focus ring: `#568F61`

#### Shape, spacing, and typography

- Use a consistent 4px/8px spacing rhythm.
- Use medium radii (8–12px) for inputs, buttons, and candidate rows; 14–18px only for major containers. Avoid rounding every element into a pill.
- Body text: comfortable 14–16px, line-height around 1.55–1.7.
- Main discovery heading: responsive 30–42px, medium or semibold, tight but readable tracking.
- Section headings: 16–20px. Metadata: 12–13px with adequate contrast.
- Prefer the existing bundled font. Otherwise use a clean UI sans-serif such as Inter with system fallbacks. Use italics selectively for scientific binomials, not for general UI copy.
- Keep transitions mostly in the 140–220ms range, using reduced-motion-aware behavior.

---

## 3. App shell and navigation

Build a consistent application shell that feels familiar to a modern AI workspace.

### Desktop layout

- **Left sidebar:** approximately 248–272px when expanded; collapsible to an icon rail if practical.
- **Main workspace:** fills remaining width and owns the current discovery or conversation view.
- Center readable content within a maximum width of approximately 800–900px. Do not stretch chat messages or the discovery form across a very wide monitor.
- Use thin dividers and surface contrast to distinguish the sidebar from the workspace; avoid a thick framed-panel look.

### Sidebar content

1. A compact product wordmark such as **Medicinal Plant Explorer**. Keep the full academic project title in the document title/About area, not as a huge sidebar heading.
2. A prominent **New exploration** action. It must create a new session in discovery mode, not open a blank general chat.
3. A compact navigation area only for routes/features that actually exist in the project. Do not invent nonfunctional destinations.
4. Recent sessions, with plant name or user-given title, a subtle status/preview, and standard overflow actions only when implemented.
5. A clear selected-session state, keyboard-accessible controls, tooltips for icon-only buttons, and a sensible empty state when history is empty.
6. A restrained footer area for settings/theme or project information only if those features exist or are implemented correctly.

### Session list behavior

- The currently selected session must be visually distinct without using a loud filled card for every row.
- Truncate long titles cleanly and show the full title on hover/focus where appropriate.
- Support loading, empty, and failed-to-load history states.
- Do not display fake conversations or hardcoded history as real user data.

### Mobile layout

- Replace the persistent sidebar with a drawer opened by a top-left menu button.
- Keep the current plant/context visible in the top bar without consuming the entire screen.
- Keep primary actions reachable with one hand and prevent the keyboard from obscuring the active composer or upload controls.

---

## 4. Plant discovery experience

### 4.1 Entry state

Every brand-new session opens on a dedicated discovery screen. Do not show the regular chat transcript or an unqualified “Ask anything…” input before a plant has been established.

Use a calm, spacious center composition with:

- Small botanical/product identifier (wordmark or simple leaf mark).
- Main heading: **“What plant would you like to explore?”**
- Supporting line: **“Search by name, describe what you know, or identify a plant from a photo.”**
- A single, prominent discovery workspace with clearly labelled modes.
- A few optional example chips such as `Ashwagandha`, `Tulsi`, and `Neem`. Selecting an example should populate or submit the relevant discovery input; do not imply a match before the backend resolves it.
- Short, unobtrusive note that plant identity may need confirmation when multiple matches are plausible.

The first screen should not be a grid of large feature cards. Use a single cohesive discovery composer and lightweight controls.

### 4.2 Discovery modes

Present all four methods clearly in a compact tab/segmented-control row or similarly understandable selector:

- **Plant name** — canonical/common/scientific name search with autocomplete.
- **Describe** — natural-language description of the plant or what the user is trying to identify.
- **Photo** — upload or drag-and-drop an image of the whole plant, leaf, flower, root, or specimen.
- **Text + photo** — allow a textual guess or context alongside an image.

Changing modes must preserve entered text and any selected image where sensible. It must not unexpectedly submit or discard work.

### 4.3 Name search and autocomplete

- Use a real search field with a visible label and helpful placeholder, for example **“Search common or scientific name…”**.
- Show a clear focus state, a search icon, a keyboard-accessible clear action, and loading feedback while suggestions load.
- Debounce requests using existing frontend conventions and cancel or disregard stale responses so older queries do not overwrite newer results.
- Support arrow-key navigation, Enter to select, Escape to dismiss, and proper combobox/listbox semantics.
- Suggestions may show common/canonical name as the primary line, scientific name in italic as the secondary line, and a concise category or alias only where returned by the search system.
- Prioritize canonical names, scientific names, common names, Sanskrit/Hindi/regional names, aliases, and fuzzy matches according to the existing search contract. Do not create a separate frontend-only ranking algorithm.
- Selecting a suggestion should establish the candidate input, but where the workflow requires explicit confirmation, do not jump into conversation before that confirmation.
- Include distinct states for suggestions loading, no matches, search error, and no query entered.

### 4.4 Natural-language description

- Label the textarea as plant-specific, e.g. **“Describe the plant or what you know about it”**. Do not label it as a general-purpose chat box.
- Give an example placeholder such as **“I’m looking for a medicinal plant with…”**.
- Support multiline input and a clear primary action such as **Find plant**.
- Allow the user to describe appearance, local name, plant part, habitat, or context without requiring every detail.
- Validation should be helpful, not punitive. Keep the description when the request fails or needs clarification.

### 4.5 Image upload

- Support click-to-select and drag-and-drop where the browser and current stack allow it.
- Provide a clear drop zone with camera/image icon, concise guidance, and accepted file types/size based on the actual backend contract. Do not invent upload limits.
- Show a local preview, filename, remove/replace action, upload/analysis status, and an accessible description for the preview.
- Support image-only and text-plus-image submissions.
- Validate unsupported or oversized files before submission when the actual constraints are known; explain the problem in plain language and allow recovery.
- Include uploading, uploaded, processing, failure, retry, and remove states. Do not represent a local preview as a successful identification.
- Never reuse a previous user's or previous session's image unintentionally.

### 4.6 Discovery submission and progress

- Disable duplicate submission while the same request is in flight, but preserve a clear way to cancel or recover if the API supports it.
- Give the user immediate acknowledgement after submission.
- When backend status events are available, map them to calm, user-facing labels such as **“Checking possible plant names”**, **“Comparing the available clues”**, and **“Narrowing the matches”**.
- Progress should be honest and event-driven. If the backend provides no granular progress, use a simple loading indicator and one stable status message; do not animate fabricated steps or expose internal prompts, hidden reasoning, agent instructions, raw execution traces, or internal tool payloads.
- Preserve the input on network/server errors and show a direct retry action.

### 4.7 Candidate and clarification interface

If discovery is unresolved or ambiguous, show a clear explanation such as **“I found a few possible matches. Which one looks right?”** followed by ranked candidates.

Each candidate row/card may contain only fields the backend actually supplies, for example:

- Common/canonical plant name.
- Scientific name, formatted in italics.
- Relevant aliases or plant part, when applicable.
- A concise, user-understandable match indicator if confidence is supplied and approved for display. Prefer terms such as **Strong match**, **Possible match**, or **Needs confirmation** over false precision. Do not invent percentages or confidence values.
- One clear action: **Explore this plant** or **Select this plant**.

Design candidates as compact, information-rich rows or modest cards—not a wall of large colorful tiles. Selection should have a visible selected state and keyboard support.

Clarification controls must:

- Make the question specific and easy to answer.
- Support choosing a candidate or entering a correction/alternate name.
- Keep the user's original text and image available where helpful.
- Clearly separate **Confirm selection** from **Try another search**.
- Preserve the existing session and pending discovery context after the user answers. Do not silently create a new chat or lose the conversation lineage.

If no candidate can be responsibly presented, show an honest unresolved state and invite a narrower description, another name, or a clearer image. Do not force a selection.

---

## 5. Plant-confirmation transition

After the identity is established through the workflow, show a brief, polished confirmation moment before the regular chat begins. It should feel like a natural step forward, not a blocking splash screen.

Display a compact **Plant identified** / **Plant selected** summary with:

- The confirmed plant name.
- Scientific name if available.
- A trustworthy plant image only if one is supplied by the system; otherwise use a simple botanical icon or neutral placeholder, never a fabricated photo.
- Optional selected plant part, if already established.
- A clear next action such as **Start exploring** / **Continue to chat**.

Offer lightweight suggested topics that map to capabilities actually exposed by the project, for example:

- Overview
- Plant parts
- Phytochemicals
- Bioactivities
- Protein targets
- Traditional uses
- Scientific evidence

These should be prompts or shortcuts into the conversation, not claims that those topics have results. Hide or disable any topic that the backend does not support. Do not present traditional use as proof of clinical efficacy.

When the user continues, enter conversation mode with the plant context visibly attached to the session. Keep the transition quick; avoid a long animation.

---

## 6. Conversation experience

### 6.1 Layout

Use a familiar modern AI chat composition:

- A compact top bar with the active plant and, if known, its scientific name.
- A readable central transcript column, maximum width approximately 760–820px.
- User messages aligned consistently on one side with a restrained surface background.
- Assistant answers primarily on the workspace background with clear typographic hierarchy, rather than placing every answer in a large colored bubble.
- A composer anchored at the bottom of the conversation area, with enough bottom padding so the last answer is never obscured.
- A small footer note for appropriate non-diagnostic / evidence limitations only if it aligns with the project's product/legal wording. Avoid loud or repetitive disclaimers.

The chat should be comfortable for long answers with headings, lists, tables, inline citations, evidence sections, and responsive images where available. Scientific names should be italicized correctly. Tables must scroll horizontally on narrow screens rather than break the whole layout.

### 6.2 Message rendering

- Stream assistant responses incrementally when the API supports streaming. Preserve markdown rendering during streaming and avoid visible layout jumps.
- Support paragraphs, headings, lists, tables, code only where relevant, links, and citations/evidence references from the defined response contract.
- Distinguish citations from ordinary links. Citation interaction should open the relevant source details or evidence view only when such a feature exists.
- Do not fabricate sources, citations, evidence ratings, plant photos, or evidence metadata in the frontend.
- Provide copy-answer and copy-section actions where useful, with clear keyboard and screen-reader labels. Add regenerate/retry only if the underlying action is supported.
- Avoid a toolbar full of controls on every message. Show secondary controls on hover/focus on desktop and make them reachable on touch screens.
- Render empty, streaming, completed, failed, and interrupted answer states distinctly.

### 6.3 Composer

- Multi-line composer with auto-growing height up to a reasonable maximum; after the maximum, scroll inside the input.
- Placeholder should be contextual, e.g. **“Ask about Ashwagandha…”**, based on the active plant.
- Send button with a clear disabled/loading state. Enter sends only if that convention is clearly communicated; Shift+Enter inserts a newline. On mobile, respect the software keyboard's send action where possible.
- Keep the active plant/context visible without repeating the entire plant name in every visual element.
- If image attachments are supported during follow-up, expose the same clear upload affordance and preview/retry/remove states. Do not imply conversational image analysis if the API does not support it.
- On submit, keep the user's message visible immediately and show a discreet assistant response indicator.
- Prevent accidental duplicate sends. Keep the draft after recoverable errors.

### 6.4 Follow-up context and changing plants

- Follow-up questions about the active plant should look and feel like normal conversation; do not make users select the same plant again on every turn.
- Keep the active plant identifier in a compact top-bar context chip/menu. If changing the active plant is supported, require an explicit action and make its effect clear.
- When a user mentions a different plant and the existing resolution workflow requests clarification, present that clarification inline in the conversation. Do not unexpectedly erase the current transcript or reset the whole session.
- When an inline plant change is confirmed, visibly update the active plant context. Preserve prior conversation history and make the context switch understandable.
- Keep clarification as an interrupt-and-resume interaction: render the question and its choices in the transcript, preserve the pending state, and continue the same session after the user responds.

### 6.5 Progress while investigating

Use a calm, compact progress component near the pending assistant turn. Prefer a short status line and subtle spinner/progress indicator over a large full-screen loader.

Examples of acceptable user-facing copy:

- “Reviewing the available evidence…”
- “Checking related plant information…”
- “Comparing the findings…”
- “Preparing a sourced answer…”

Only show stages that correspond to actual status information or a truthful generic pending state. The UI must not expose hidden chain-of-thought, raw agent conversations, internal prompts, unrestricted traces, internal state dumps, or raw orchestration payloads. A user-friendly, high-level status indicator is enough.

If the investigation needs user input, stop the generic spinner and present the clarification inline with obvious response controls. Do not make the user think the system is still working while it is waiting for them.

### 6.6 Evidence and responsible claims

- Present source/citation information consistently and close to the claim it supports.
- Where the response contract labels evidence classes, use quiet text labels or compact badges, for example **Traditional**, **Preclinical**, **Animal study**, **Clinical**, or **Mechanistic**. Do not imply these categories are interchangeable.
- Avoid green success styling for every positive claim; color is not evidence strength.
- Do not translate traditional use, in-vitro evidence, or animal findings into a clinical recommendation.
- If source data is unavailable, show that limitation plainly rather than making the page look complete with placeholder sources.

---

## 7. Loading, errors, empty states, and recovery

Every important network-backed view needs designed states; do not leave raw browser alerts, blank panels, or unhandled exceptions in the UI.

- **Initial load:** stable shell/skeleton; no large flickering layout shifts.
- **Search loading:** small inline progress indicator beside suggestions.
- **No matches:** explain that no clear match was found and provide a next step.
- **Ambiguity:** candidate choices and a clear clarification question.
- **Image failure:** preserve the file where possible and allow retry or replacement.
- **Network/API failure:** concise explanation, retry action, keep the user's input.
- **Streaming failure:** preserve already received content when safe, mark the answer incomplete, and offer retry if supported.
- **Waiting for user:** stop progress animation and make the pending question/choice prominent.
- **No session history:** simple informative empty state with a New exploration action.
- **Session restore:** restore the correct active plant and mode from persisted state; never infer a confirmed plant just from the session title.
- **Abstention/unresolved result:** communicate that a reliable match or answer could not be established and provide a useful next action.

Use plain language, not stack traces or raw backend error messages. Put technical details in the developer console only when appropriate and never expose secrets or internal prompts to the user.

---

## 8. Responsive behavior

### Desktop (`>= 1024px`)

- Persistent sidebar, centered discovery/composer, readable transcript width.
- Candidate results can use a compact list or two-column layout only when each item remains easy to compare.
- Hover controls may reveal secondary actions, but keyboard focus must reveal them too.

### Tablet (`768–1023px`)

- Collapsible sidebar or narrower drawer.
- Reduce horizontal padding and preserve a readable content maximum width.
- Keep candidate information stacked when side-by-side presentation becomes cramped.

### Mobile (`< 768px`)

- Drawer navigation, compact top bar, single-column content.
- Discovery mode selector must remain usable without horizontal overflow.
- Full-width primary controls; candidate actions easy to tap.
- Upload drop zone must still have a tap-to-select fallback.
- Composer grows above the keyboard; avoid fixed-height containers that clip the final answer.
- Citation popovers/menus must fit the viewport and be dismissible.
- No hover-only interactions.

Test at least one narrow mobile width, one tablet width, and a common desktop width before considering the UI complete.

---

## 9. Accessibility and interaction quality

- Use semantic HTML and accessible names for all icon-only controls.
- Ensure full keyboard navigation through sidebar, discovery modes, autocomplete, candidate selection, clarification controls, citations, and composer.
- Use visible focus indicators that meet contrast requirements.
- Keep text contrast readable in both themes and do not use color alone to convey match state, errors, or evidence type.
- Add suitable labels/announcements for upload status, search results, streaming state, errors, and clarification requests. Avoid announcing every streamed token to assistive technology; announce meaningful status changes.
- Respect `prefers-reduced-motion` and do not rely on animation to explain a state transition.
- Make buttons, list options, and touch targets sufficiently large, particularly on mobile.
- Ensure menus/popovers/dialogs have predictable focus and dismissal behavior.

---

## 10. Motion and micro-interactions

Use motion sparingly to clarify cause and effect:

- Fast, subtle hover/focus transitions on buttons, suggestion rows, and navigation.
- Smooth but restrained reveal of candidate results and clarification controls.
- A short confirmation transition into conversation mode.
- A gentle streaming cursor/indicator only while genuinely streaming.
- Small file-preview entrance/removal animation, respecting reduced-motion settings.

Do not use perpetual animation, exaggerated spring motion, parallax, large page transitions, or effects that slow the demo.

---

## 11. Implementation boundaries for Codex

Implement this as a frontend design and UX task only.

1. Inspect the current project and follow the existing framework, routing, styling, API clients, type definitions, and component conventions.
2. Reuse existing contracts and endpoints for autocomplete, resolution, uploads, candidate selection, session restoration, streaming, clarifications, and citations. Do not rename or redesign backend contracts in order to make the UI convenient.
3. Keep UI state and presentation separate from agent/orchestration implementation. The frontend should consume supported user-facing response/status data; it must not implement agent logic or duplicate entity-resolution ranking.
4. Do not introduce a fourth agent, a new orchestrator, or backend architecture changes. Do not modify the existing state/decision/evidence model as part of this task.
5. If a UI element depends on a missing backend capability, create a clean typed integration boundary and clearly document the dependency. Do not make a decorative control look functional when it is not connected. Use mock data only in an explicit development/demo mode and label it as sample data.
6. Do not hardcode successful plant identifications, fabricated confidence percentages, invented citations, or fake progress milestones. Real responses must be driven by API data.
7. Keep code modular and readable. Build or reuse components for the app shell, sidebar/session list, discovery mode selector, autocomplete, upload/preview, candidate selection, clarification prompt, active-plant header, transcript/message renderer, evidence/citation UI, composer, and progress/error states.
8. Preserve existing features and API behavior. Avoid unnecessary dependencies and broad refactors. Use the existing icon, markdown, and styling libraries if present.
9. Add clear types for loading/success/empty/error/pending-clarification states where the existing contracts allow it. Make event handling resilient to stale requests, repeated submissions, and component unmounts.
10. Ensure there are no dead buttons, fake links, placeholder routes, or inaccessible icon-only controls in the finished UI.

---

## 12. Definition of done

The frontend is ready for the MVP demo when all of the following are true:

- [ ] A new session always opens in Plant Discovery, never directly in unrestricted conversation.
- [ ] Plant name search includes responsive, keyboard-accessible autocomplete.
- [ ] Natural-language description works as a distinct discovery path.
- [ ] Image upload supports preview, remove/replace, validation based on actual constraints, loading, and recovery.
- [ ] Text and image can be submitted together when supported by the existing API contract.
- [ ] Ambiguous results render useful candidate options and explicit confirmation/clarification controls.
- [ ] The user can confirm a plant and transition into conversation mode.
- [ ] The confirmed plant and scientific name, when available, stay visible during follow-up conversation.
- [ ] Assistant responses stream when supported and render readable rich text, citations, and evidence metadata supplied by the backend.
- [ ] Waiting, clarification, failure, retry, and completion states are visually and behaviorally distinct.
- [ ] The UI never exposes hidden chain-of-thought, private prompts, raw agent messages, or unrestricted execution traces.
- [ ] The interface has no fabricated plant results, invented citations, or misleading progress indicators.
- [ ] The app is visually coherent, responsive, keyboard-accessible, and free of console errors introduced by this work.
- [ ] Existing backend architecture and contracts remain unchanged.

**Final quality bar:** this should look and feel like a thoughtfully designed, near-production AI research product—not a generic chatbot skin, a component-library demo, or a dashboard full of cards.
