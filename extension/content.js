/**
 * OwlThread In-Page Content Script
 * - Isolated via Shadow DOM
 * - First-visit domain permission prompt
 * - Floating Owl Widget with 3 options:
 *   1. Save this address
 *   2. Stop reading / Resume
 *   3. Write a new note
 * - Clean visible text extraction & ambient syncing
 */

(function () {
  // Prevent duplicate injection
  if (window.__owlthread_injected) return;
  window.__owlthread_injected = true;

  // Ignore internal chrome pages or iframes if not top
  if (window.location.protocol === "chrome:" || window.location.protocol === "chrome-extension:") {
    return;
  }

  const hostname = window.location.hostname || "local";
  const currentUrl = window.location.href;
  const pageTitle = document.title || "Untitled Page";

  let sitePermission = "unknown"; // "allowed", "blocked", "paused", "unknown"
  let isReadingActive = false;
  let isMenuOpen = false;
  let isNoteComposerOpen = false;
  let lastCapturedTextHash = "";
  let currentActiveProject = "General";

  // -------------------------------------------------------------
  // 1. Shadow DOM Host Setup
  // -------------------------------------------------------------
  const hostElement = document.createElement("div");
  hostElement.id = "owlthread-shadow-host";
  hostElement.style.all = "initial";
  hostElement.style.position = "fixed";
  hostElement.style.zIndex = "2147483647";
  hostElement.style.bottom = "24px";
  hostElement.style.right = "24px";
  hostElement.style.pointerEvents = "none"; // allow click-through for transparent zones

  const shadowRoot = hostElement.attachShadow({ mode: "open" });
  document.documentElement.appendChild(hostElement);

  // -------------------------------------------------------------
  // 2. Scoped Shadow DOM CSS Styles
  // -------------------------------------------------------------
  const styleEl = document.createElement("style");
  styleEl.textContent = `
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    .owl-container {
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      pointer-events: auto;
      user-select: none;
    }

    /* Living Duolingo-Style Owl Character */
    .owl-trigger-btn {
      width: 58px;
      height: 64px;
      background: transparent;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
      outline: none;
      padding: 0;
      filter: drop-shadow(0 8px 18px rgba(15, 23, 42, 0.55));
    }

    .owl-trigger-btn:hover {
      transform: scale(1.12) translateY(-3px);
      filter: drop-shadow(0 12px 28px rgba(99, 102, 241, 0.6));
    }

    .owl-trigger-btn:active {
      transform: scale(0.96);
    }

    .owl-svg {
      width: 58px;
      height: 64px;
      overflow: visible;
    }

    /* Living animation: subtle breathing */
    .owl-body-group {
      transform-origin: 64px 110px;
      animation: owlBreathe 3.5s ease-in-out infinite;
    }

    @keyframes owlBreathe {
      0%, 100% { transform: translateY(0) scaleY(1); }
      50% { transform: translateY(-1.5px) scaleY(1.02); }
    }

    /* Blinking eyelids */
    .owl-eyelid {
      transform-origin: center top;
      transition: transform 0.08s ease;
      opacity: 0;
    }
    .owl-eyelid.blinking {
      opacity: 1;
    }

    /* Eye pupils tracking mouse cursor */
    .owl-pupil {
      transition: transform 0.05s ease-out;
      will-change: transform;
    }

    /* Notebook & Pencil Layer */
    .owl-notebook {
      transform-origin: 36px 80px;
      transition: all 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
      opacity: 0;
      transform: translateY(16px) scale(0.6);
      pointer-events: none;
    }
    .owl-trigger-btn.writing .owl-notebook {
      opacity: 1;
      transform: translateY(0) scale(1);
    }

    .owl-pencil {
      transform-origin: 52px 64px;
    }
    .owl-trigger-btn.writing .owl-pencil {
      animation: owlScribble 0.18s ease-in-out infinite alternate;
    }

    @keyframes owlScribble {
      0% { transform: translate(0, 0) rotate(-6deg); }
      100% { transform: translate(4px, -2px) rotate(14deg); }
    }

    /* Success Pop Checkmark Badge */
    .owl-check-badge {
      transform-origin: 64px 16px;
      transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
      opacity: 0;
      transform: scale(0) translateY(10px);
      pointer-events: none;
    }
    .owl-trigger-btn.saved .owl-check-badge {
      opacity: 1;
      transform: scale(1) translateY(0);
      animation: badgeBounce 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    @keyframes badgeBounce {
      0% { transform: scale(0) translateY(10px); }
      60% { transform: scale(1.3) translateY(-4px); }
      100% { transform: scale(1) translateY(0); }
    }

    /* Head tilt / happy wink on saved */
    .owl-trigger-btn.saved .owl-head-group {
      animation: owlHappyWink 1.4s ease forwards;
    }
    @keyframes owlHappyWink {
      0% { transform: rotate(0deg); }
      20% { transform: rotate(-8deg); }
      70% { transform: rotate(-8deg); }
      100% { transform: rotate(0deg); }
    }

    /* Status Pulse Beacon */
    .status-beacon {
      position: absolute;
      top: 2px;
      right: 4px;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      border: 2px solid #0f172a;
      background-color: #f59e0b;
      box-shadow: 0 0 6px rgba(0, 0, 0, 0.4);
      transition: background-color 0.3s ease;
      z-index: 5;
    }

    .status-beacon.reading {
      background-color: #22c55e;
      box-shadow: 0 0 8px #22c55e;
      animation: pulse 2s infinite;
    }

    .status-beacon.paused {
      background-color: #f59e0b;
      box-shadow: 0 0 6px #f59e0b;
    }

    .status-beacon.blocked {
      background-color: #64748b;
      box-shadow: none;
    }

    .status-beacon.syncing {
      background-color: #38bdf8;
      box-shadow: 0 0 10px #38bdf8;
      transform: scale(1.2);
      transition: all 0.2s ease;
    }

    @keyframes pulse {
      0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); }
      70% { transform: scale(1.15); box-shadow: 0 0 0 8px rgba(34, 197, 94, 0); }
      100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
    }

    /* First-time Permission Prompt Card */
    .permission-card {
      position: absolute;
      bottom: 66px;
      right: 0;
      width: 320px;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 14px;
      box-shadow: 0 20px 35px -10px rgba(0, 0, 0, 0.7), 0 0 15px rgba(99, 102, 241, 0.2);
      padding: 16px;
      color: #f8fafc;
      animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      z-index: 10;
    }

    .permission-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }

    .permission-title {
      font-size: 14px;
      font-weight: 700;
      color: #e0e7ff;
    }

    .permission-text {
      font-size: 12px;
      line-height: 1.5;
      color: #94a3b8;
      margin-bottom: 14px;
    }

    .permission-domain {
      color: #38bdf8;
      font-weight: 600;
      word-break: break-all;
    }

    .permission-actions {
      display: flex;
      gap: 8px;
    }

    .btn-allow {
      flex: 1;
      background: #4f46e5;
      color: #ffffff;
      border: none;
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      transition: background 0.2s;
    }

    .btn-allow:hover {
      background: #4338ca;
    }

    .btn-deny {
      background: #1e293b;
      color: #cbd5e1;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.2s;
    }

    .btn-deny:hover {
      background: #334155;
      color: #ffffff;
    }

    /* Popover Menu Card (3 Options) */
    .menu-card {
      position: absolute;
      bottom: 66px;
      right: 0;
      width: 290px;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 14px;
      box-shadow: 0 20px 35px -10px rgba(0, 0, 0, 0.7), 0 0 15px rgba(99, 102, 241, 0.2);
      padding: 12px;
      color: #f8fafc;
      animation: slideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      z-index: 10;
    }

    .menu-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 4px 6px 10px 6px;
      border-bottom: 1px solid #1e293b;
      margin-bottom: 8px;
    }

    .menu-header-title {
      font-size: 13px;
      font-weight: 700;
      color: #e0e7ff;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .menu-status-tag {
      font-size: 10px;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
    }

    .menu-status-tag.active {
      background: rgba(34, 197, 94, 0.2);
      color: #4ade80;
    }

    .menu-status-tag.paused {
      background: rgba(245, 158, 11, 0.2);
      color: #fbbf24;
    }

    .menu-status-tag.blocked {
      background: rgba(148, 163, 184, 0.2);
      color: #94a3b8;
    }

    .menu-options {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .menu-item {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 9px 10px;
      border-radius: 8px;
      background: #1e293b;
      border: 1px solid transparent;
      color: #f8fafc;
      cursor: pointer;
      text-align: left;
      transition: all 0.15s ease;
      width: 100%;
    }

    .menu-item:hover {
      background: #334155;
      border-color: #6366f1;
      transform: translateX(-2px);
    }

    .menu-item-icon {
      font-size: 16px;
      margin-top: 1px;
      flex-shrink: 0;
    }

    .menu-item-content {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .menu-item-title {
      font-size: 12px;
      font-weight: 600;
      color: #ffffff;
    }

    .menu-item-desc {
      font-size: 10.5px;
      color: #94a3b8;
      line-height: 1.3;
    }

    /* Note Composer Modal inside Shadow DOM */
    .note-composer {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-top: 6px;
      padding-top: 8px;
      border-top: 1px solid #334155;
    }

    .note-textarea {
      width: 100%;
      height: 75px;
      background: #020617;
      border: 1px solid #475569;
      border-radius: 6px;
      color: #f8fafc;
      font-size: 11.5px;
      padding: 8px;
      resize: none;
      outline: none;
    }

    .note-textarea:focus {
      border-color: #818cf8;
      box-shadow: 0 0 0 1px #818cf8;
    }

    .note-actions {
      display: flex;
      justify-content: flex-end;
      gap: 6px;
    }

    .btn-save-note {
      background: #22c55e;
      color: #ffffff;
      border: none;
      border-radius: 6px;
      padding: 5px 12px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }

    .btn-save-note:hover {
      background: #16a34a;
    }

    .btn-cancel-note {
      background: #334155;
      color: #cbd5e1;
      border: none;
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 11px;
      cursor: pointer;
    }

    /* In-Page Toast Alert */
    .owl-toast {
      position: absolute;
      bottom: 66px;
      right: 0;
      background: #1e1b4b;
      border: 1px solid #6366f1;
      color: #ffffff;
      padding: 10px 14px;
      border-radius: 10px;
      font-size: 12px;
      font-weight: 600;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6);
      display: flex;
      align-items: center;
      gap: 8px;
      animation: fadeIn 0.2s ease;
      white-space: nowrap;
      z-index: 20;
    }

    /* Auto-flip menus downwards when widget is dragged to top half of screen */
    .owl-container[data-flip="top"] .menu-card,
    .owl-container[data-flip="top"] .permission-card,
    .owl-container[data-flip="top"] .owl-toast {
      bottom: auto;
      top: 66px;
      animation: slideDown 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }

    @keyframes slideDown {
      from { opacity: 0; transform: translateY(-12px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @keyframes slideUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: scale(0.95); }
      to { opacity: 1; transform: scale(1); }
    }
  `;
  shadowRoot.appendChild(styleEl);

  // -------------------------------------------------------------
  // 3. UI Structure in Shadow Root
  // -------------------------------------------------------------
  const container = document.createElement("div");
  container.className = "owl-container";
  shadowRoot.appendChild(container);

  // Owl Trigger Button with Beacon & Living Mascot Elements
  const triggerBtn = document.createElement("button");
  triggerBtn.className = "owl-trigger-btn";
  triggerBtn.title = "OwlThread Ambient Memory";
  triggerBtn.innerHTML = `
    <svg class="owl-svg" viewBox="0 0 128 128" width="58" height="64" style="overflow:visible;">
      <defs>
        <linearGradient id="owlBodyGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#312e81" />
          <stop offset="60%" stop-color="#1e1b4b" />
          <stop offset="100%" stop-color="#0f172a" />
        </linearGradient>
      </defs>

      <g class="owl-body-group">
        <!-- Feet -->
        <ellipse cx="48" cy="112" rx="7" ry="4" fill="#f59e0b" />
        <ellipse cx="80" cy="112" rx="7" ry="4" fill="#f59e0b" />

        <!-- Main Body -->
        <path d="M28 54 C28 32 44 26 64 26 C84 26 100 32 100 54 C100 84 94 110 64 110 C34 110 28 84 28 54 Z"
              fill="url(#owlBodyGrad)" stroke="#4f46e5" stroke-width="2.5" />

        <!-- Wings -->
        <path d="M26 56 C22 72 26 94 40 102 C34 88 32 72 36 58 Z" fill="#312e81" stroke="#4338ca" stroke-width="1.5" />
        <path d="M102 56 C106 72 102 94 88 102 C94 88 96 72 92 58 Z" fill="#312e81" stroke="#4338ca" stroke-width="1.5" />

        <!-- Belly Patch -->
        <ellipse cx="64" cy="80" rx="22" ry="24" fill="#1e1b4b" stroke="#6366f1" stroke-width="1.5" />
        <!-- Feather Chevrons -->
        <path d="M54 74 L64 80 L74 74" fill="none" stroke="#6366f1" stroke-width="2" stroke-linecap="round" />
        <path d="M56 84 L64 90 L72 84" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" />
        <path d="M58 94 L64 98 L70 94" fill="none" stroke="#818cf8" stroke-width="1.8" stroke-linecap="round" />

        <!-- Head Group -->
        <g class="owl-head-group" style="transform-origin: 64px 50px;">
          <!-- Feather Ears/Tufts -->
          <path d="M34 34 L48 44 L38 18 Z" fill="#818cf8" stroke="#4f46e5" stroke-width="1.5" />
          <path d="M94 34 L80 44 L90 18 Z" fill="#818cf8" stroke="#4f46e5" stroke-width="1.5" />

          <!-- Face Mask -->
          <path d="M34 44 C44 38 56 42 64 46 C72 42 84 38 94 44 C98 56 96 70 92 78 C84 88 74 90 64 90 C54 90 44 88 36 78 C32 70 30 56 34 44 Z"
                fill="#0f172a" stroke="#6366f1" stroke-width="2.5" />

          <!-- Eyebrow Ridge -->
          <path d="M36 46 Q50 38 62 48 L64 49 L66 48 Q78 38 92 46" fill="none" stroke="#a5b4fc" stroke-width="3" stroke-linecap="round" />

          <!-- Left Eye Sclera -->
          <circle cx="48" cy="62" r="13" fill="#ffffff" stroke="#312e81" stroke-width="2" />
          <!-- Left Pupil (Trackable) -->
          <g id="owl-pupil-l" class="owl-pupil">
            <circle cx="48" cy="62" r="7" fill="#090d16" />
            <circle cx="48" cy="62" r="4.2" fill="#38bdf8" />
            <circle cx="49.5" cy="60.5" r="1.8" fill="#ffffff" />
          </g>
          <!-- Left Eyelid -->
          <ellipse id="owl-eyelid-l" class="owl-eyelid" cx="48" cy="62" rx="13" ry="13" fill="#312e81" />

          <!-- Right Eye Sclera -->
          <circle cx="80" cy="62" r="13" fill="#ffffff" stroke="#312e81" stroke-width="2" />
          <!-- Right Pupil (Trackable) -->
          <g id="owl-pupil-r" class="owl-pupil">
            <circle cx="80" cy="62" r="7" fill="#090d16" />
            <circle cx="80" cy="62" r="4.2" fill="#38bdf8" />
            <circle cx="81.5" cy="60.5" r="1.8" fill="#ffffff" />
          </g>
          <!-- Right Eyelid -->
          <ellipse id="owl-eyelid-r" class="owl-eyelid" cx="80" cy="62" rx="13" ry="13" fill="#312e81" />

          <!-- Golden Beak -->
          <polygon points="64,74 58,64 70,64" fill="#f59e0b" stroke="#d97706" stroke-width="1" />
        </g>

        <!-- Notebook & Pencil Accessory Layer (Notes Scribbling) -->
        <g id="owl-notebook-layer" class="owl-notebook">
          <rect x="22" y="66" width="26" height="32" rx="4" fill="#f8fafc" stroke="#6366f1" stroke-width="2" />
          <rect x="22" y="66" width="26" height="8" rx="3" fill="#4f46e5" />
          <line x1="26" y1="65" x2="26" y2="69" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" />
          <line x1="32" y1="65" x2="32" y2="69" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" />
          <line x1="38" y1="65" x2="38" y2="69" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" />
          <line x1="44" y1="65" x2="44" y2="69" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" />
          <line x1="26" y1="78" x2="44" y2="78" stroke="#cbd5e1" stroke-width="1.5" stroke-linecap="round" />
          <line x1="26" y1="83" x2="42" y2="83" stroke="#cbd5e1" stroke-width="1.5" stroke-linecap="round" />
          <line x1="26" y1="88" x2="38" y2="88" stroke="#38bdf8" stroke-width="1.5" stroke-linecap="round" />
          <g class="owl-pencil">
            <polygon points="48,84 56,66 60,68 50,88" fill="#f59e0b" />
            <polygon points="48,84 46,90 50,88" fill="#334155" />
            <rect x="55" y="63" width="6" height="4" rx="1" fill="#ec4899" transform="rotate(26 55 63)" />
          </g>
        </g>

        <!-- Success Checkmark Badge Layer -->
        <g id="owl-check-layer" class="owl-check-badge">
          <circle cx="64" cy="18" r="14" fill="#22c55e" stroke="#ffffff" stroke-width="2.5" />
          <path d="M57 18 L62 23 L72 13" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
        </g>
      </g>
    </svg>
    <div class="status-beacon" id="owl-beacon"></div>
  `;
  container.appendChild(triggerBtn);

  const beaconEl = triggerBtn.querySelector("#owl-beacon");
  const pupilL = triggerBtn.querySelector("#owl-pupil-l");
  const pupilR = triggerBtn.querySelector("#owl-pupil-r");
  const eyelidL = triggerBtn.querySelector("#owl-eyelid-l");
  const eyelidR = triggerBtn.querySelector("#owl-eyelid-r");

  let isWritingAnimationActive = false;

  // Eye-tracking mouse follower physics
  window.addEventListener("mousemove", (e) => {
    if (isWritingAnimationActive) return;
    const rect = triggerBtn.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = e.clientX - cx;
    const dy = e.clientY - cy;
    const angle = Math.atan2(dy, dx);
    const dist = Math.min(4.2, Math.hypot(dx, dy) / 36);
    const ox = Math.cos(angle) * dist;
    const oy = Math.sin(angle) * dist;
    if (pupilL && pupilR) {
      pupilL.style.transform = `translate(${ox}px, ${oy}px)`;
      pupilR.style.transform = `translate(${ox}px, ${oy}px)`;
    }
  });

  // Natural living blink cycle
  function scheduleNaturalBlink() {
    const delay = 3500 + Math.random() * 3000;
    setTimeout(() => {
      if (!isWritingAnimationActive && eyelidL && eyelidR) {
        eyelidL.classList.add("blinking");
        eyelidR.classList.add("blinking");
        setTimeout(() => {
          eyelidL.classList.remove("blinking");
          eyelidR.classList.remove("blinking");
          scheduleNaturalBlink();
        }, 130);
      } else {
        scheduleNaturalBlink();
      }
    }, delay);
  }
  scheduleNaturalBlink();

  // Dynamic overlays slot
  const overlaySlot = document.createElement("div");
  container.insertBefore(overlaySlot, triggerBtn);

  // Trigger Note Taking (pull out copy & pencil) + Success Checkmark
  function triggerNoteTakingAnimation(message = "Captured to Memory", quadrant = "") {
    isWritingAnimationActive = true;
    triggerBtn.classList.remove("saved");
    triggerBtn.classList.add("writing");
    flashSyncingBeacon();

    // Eyes look down towards the notebook while scribbling
    if (pupilL && pupilR) {
      pupilL.style.transform = "translate(-2px, 4px)";
      pupilR.style.transform = "translate(-2px, 4px)";
    }

    // Scribble for 1.3s -> then show celebratory saved checkmark badge!
    setTimeout(() => {
      triggerBtn.classList.remove("writing");
      triggerSavedCheckmark(message, quadrant);
    }, 1300);
  }

  function triggerSavedCheckmark(message = "Saved to Memory!", quadrant = "") {
    triggerBtn.classList.add("saved");

    // Wink right eyelid happily
    if (eyelidR) eyelidR.classList.add("blinking");

    const badgeText = quadrant ? `${message} (${quadrant}) ✓` : `${message} ✓`;
    showToast(badgeText, "🦉", 2600);

    setTimeout(() => {
      triggerBtn.classList.remove("saved");
      if (eyelidR) eyelidR.classList.remove("blinking");
      isWritingAnimationActive = false;
    }, 1800);
  }

  // -------------------------------------------------------------
  // 4. Helper & Toast Methods
  // -------------------------------------------------------------
  function showToast(message, icon = "🦉", durationMs = 2800) {
    const existing = overlaySlot.querySelector(".owl-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = "owl-toast";
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    overlaySlot.appendChild(toast);

    setTimeout(() => {
      if (toast && toast.parentNode) {
        toast.remove();
      }
    }, durationMs);
  }

  function updateBeaconStatus() {
    beaconEl.className = "status-beacon";
    if (sitePermission === "allowed" && isReadingActive) {
      beaconEl.classList.add("reading");
      beaconEl.title = "OwlThread: Ambient Memory Active";
      triggerBtn.title = `OwlThread: Active on ${hostname}`;
    } else if (sitePermission === "allowed" && !isReadingActive) {
      beaconEl.classList.add("paused");
      beaconEl.title = "OwlThread: Memory Paused (Click to Resume)";
      triggerBtn.title = `OwlThread: Paused on ${hostname}`;
    } else if (sitePermission === "blocked") {
      beaconEl.classList.add("blocked");
      beaconEl.title = "OwlThread: Blocked on this domain";
      triggerBtn.title = `OwlThread: Blocked on ${hostname}`;
    } else {
      beaconEl.classList.add("paused");
      beaconEl.title = "OwlThread: Permission Pending";
      triggerBtn.title = `OwlThread: ${hostname}`;
    }
  }

  // -------------------------------------------------------------
  // 5. Clean Visible Text Extractor
  // -------------------------------------------------------------
  function extractVisiblePageText() {
    // 1. Check user selection
    const selection = window.getSelection();
    const selText = selection ? selection.toString().trim() : "";
    if (selText.length > 20) {
      return { text: selText, type: "selection" };
    }

    // 2. Specialized Chat and Article Selectors
    const targetedSelectors = [
      '[data-message-author-role]',
      '.font-claude-message',
      'message-content',
      '.chat-message',
      '.conversation-container',
      'article',
      'main',
      '[role="main"]',
      '.markdown-body',
      '#content',
      '.post-content',
    ];

    for (const selector of targetedSelectors) {
      const elements = document.querySelectorAll(selector);
      if (elements.length > 0) {
        const textParts = Array.from(elements)
          .map((el) => el.innerText.trim())
          .filter((t) => t.length > 30);
        if (textParts.length > 0) {
          return {
            text: textParts.join("\n\n---\n\n"),
            type: `targeted (${selector})`,
          };
        }
      }
    }

    // 3. Clean full document visible body text
    const clone = document.body.cloneNode(true);
    // Remove unwanted non-text tags
    const toRemove = clone.querySelectorAll("script, style, noscript, svg, nav, footer, iframe, header");
    toRemove.forEach((n) => n.remove());

    const cleanedText = clone.innerText.trim();
    if (cleanedText.length > 40) {
      return { text: cleanedText, type: "page_body" };
    }

    return { text: "", type: "empty" };
  }

  // -------------------------------------------------------------
  // 6. Live Chunking & Zero-Data-Loss Persistent Buffer
  // -------------------------------------------------------------
  const CHUNKS_STORAGE_KEY = `owl_chunks_${hostname}`;
  let activeChunksQueue = [];
  let isDrainingChunks = false;
  let sessionChunkCount = 0;
  const recentCapturedHashes = new Set();

  function flashSyncingBeacon() {
    beaconEl.classList.add("syncing");
    setTimeout(() => {
      beaconEl.classList.remove("syncing");
      updateBeaconStatus();
    }, 850);
  }

  // Persist current active queue to chrome.storage.local (zero data loss on sudden close)
  function persistActiveChunksQueue() {
    if (!chrome.runtime?.id) return;
    try {
      const data = {};
      data[CHUNKS_STORAGE_KEY] = activeChunksQueue;
      chrome.storage.local.set(data, () => {
        if (chrome.runtime?.lastError) {}
      });
    } catch (e) {}
  }

  // Restore any pending chunks from local storage (e.g. from previously closed tabs)
  function restorePendingChunksFromStorage() {
    if (!chrome.runtime?.id) return;
    try {
      chrome.storage.local.get([CHUNKS_STORAGE_KEY], (res) => {
        if (chrome.runtime?.lastError) return;
        const stored = res && res[CHUNKS_STORAGE_KEY];
        if (Array.isArray(stored) && stored.length > 0) {
          activeChunksQueue.push(...stored);
          console.log(`[OwlThread] Restored ${stored.length} unsent chunk(s) from storage for ${hostname}`);
          drainChunksQueue();
        }
      });
    } catch (e) {}
  }

  async function syncCaptureToOwlThread(payload) {
    if (!chrome?.runtime?.id) {
      return { success: false, error: "Extension context invalidated" };
    }

    try {
      const res = await chrome.runtime.sendMessage({
        action: "send_capture",
        payload: {
          text: payload.text,
          url: payload.url || currentUrl,
          title: payload.title || pageTitle,
          source_app: payload.source_app || "browser",
          project_name: payload.project_name || currentActiveProject,
          metadata: {
            container_type: payload.type || payload.container_type || "ambient",
            hostname: hostname,
            timestamp: payload.timestamp || new Date().toISOString(),
            ...(payload.metadata || {}),
          },
        },
      }).catch((err) => {
        return { success: false, error: err ? err.message : "Runtime disconnected" };
      });

      return res || { success: false };
    } catch (err) {
      return { success: false, error: err ? err.message : "Runtime disconnected" };
    }
  }

  // Capture a discrete chunk (user message, assistant reply, selection, note, etc.)
  async function captureChunk(chunkText, chunkType, extraMetadata = {}) {
    if (sitePermission !== "allowed" || !isReadingActive) return;
    if (!chunkText || typeof chunkText !== "string") return;

    const trimmed = chunkText.trim();
    if (trimmed.length < 4) return;

    // Deduplication check: ignore if recently captured identical chunk
    const chunkHash = trimmed.slice(0, 100) + "_" + trimmed.length;
    if (recentCapturedHashes.has(chunkHash)) return;
    recentCapturedHashes.add(chunkHash);
    if (recentCapturedHashes.size > 200) {
      const first = recentCapturedHashes.values().next().value;
      recentCapturedHashes.delete(first);
    }

    const chunkItem = {
      id: "chk_" + Date.now() + "_" + Math.random().toString(36).substr(2, 6),
      text: trimmed,
      type: chunkType || "chunk",
      url: currentUrl,
      title: pageTitle,
      source_app: "browser",
      project_name: currentActiveProject,
      timestamp: new Date().toISOString(),
      metadata: {
        container_type: chunkType || "chunk",
        hostname: hostname,
        ...extraMetadata,
      },
    };

    // 1. Add to active queue
    activeChunksQueue.push(chunkItem);
    sessionChunkCount++;

    // 2. Persist IMMEDIATELY to local storage (guarantees zero data loss if tab closes instantly)
    persistActiveChunksQueue();

    // 3. Visual pulse indicator & Duolingo scribble animation
    flashSyncingBeacon();
    triggerNoteTakingAnimation("Noted", chunkType || "Memory");

    // 4. Drain queue asynchronously
    drainChunksQueue();
  }

  // Drain chunks to backend via background script
  async function drainChunksQueue() {
    if (isDrainingChunks || activeChunksQueue.length === 0) return;
    isDrainingChunks = true;

    while (activeChunksQueue.length > 0) {
      const nextChunk = activeChunksQueue[0];
      try {
        const res = await syncCaptureToOwlThread(nextChunk);
        // If sent successfully OR queued safely into background worker queue
        if (res && (res.success || res.queued)) {
          activeChunksQueue.shift(); // Remove from tab queue
          persistActiveChunksQueue();
        } else {
          break; // Stop draining and keep remaining chunks safe in storage
        }
      } catch (err) {
        console.warn("[OwlThread] Error syncing chunk:", err);
        break;
      }
    }

    isDrainingChunks = false;
  }

  async function performAmbientRead() {
    if (sitePermission !== "allowed" || !isReadingActive) return;

    const extracted = extractVisiblePageText();
    if (!extracted.text || extracted.text.length < 30) return;

    // Avoid duplicate syncs if content hasn't changed
    const sampleHash = extracted.text.slice(0, 100) + extracted.text.length;
    if (sampleHash === lastCapturedTextHash) return;
    lastCapturedTextHash = sampleHash;

    captureChunk(extracted.text, extracted.type || "page_body", { trigger: "ambient_read" });
  }

  // -------------------------------------------------------------
  // 7. Render First-Visit Permission Prompt
  // -------------------------------------------------------------
  function renderPermissionPrompt() {
    overlaySlot.innerHTML = "";

    const card = document.createElement("div");
    card.className = "permission-card";
    card.innerHTML = `
      <div class="permission-header">
        <span style="font-size: 18px;">🦉</span>
        <span class="permission-title">Save to Memory?</span>
      </div>
      <div class="permission-text">
        Do you want OwlThread to ambiently capture insights & context from <span class="permission-domain">${hostname}</span>?
      </div>
      <div class="permission-actions">
        <button class="btn-allow" id="btn-allow-site">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
          Allow & Read
        </button>
        <button class="btn-deny" id="btn-deny-site">Not now</button>
      </div>
    `;

    overlaySlot.appendChild(card);

    card.querySelector("#btn-allow-site").onclick = () => {
      saveSitePermission("allowed");
      card.remove();
      showToast(`OwlThread memory enabled for ${hostname}!`, "✅");
      performAmbientRead();
    };

    card.querySelector("#btn-deny-site").onclick = () => {
      saveSitePermission("blocked");
      card.remove();
      showToast(`Memory capture disabled on ${hostname}`, "⚪");
    };
  }

  // -------------------------------------------------------------
  // 8. Render 3-Option Action Popover Menu
  // -------------------------------------------------------------
  function renderActionMenu() {
    overlaySlot.innerHTML = "";
    isNoteComposerOpen = false;

    const card = document.createElement("div");
    card.className = "menu-card";

    const statusLabel = isReadingActive ? "Reading" : "Paused";
    const statusClass = isReadingActive ? "active" : "paused";
    const pauseToggleText = isReadingActive ? "Stop reading" : "Resume reading";
    const pauseToggleDesc = isReadingActive
      ? "Pause automatic memory capture for this tab"
      : "Resume automatic memory capture";
    const pauseIcon = isReadingActive ? "⏸️" : "▶️";

    card.innerHTML = `
      <div class="menu-header">
        <div class="menu-header-title">
          <span>🦉</span> OwlThread
        </div>
        <div style="display:flex; align-items:center; gap:6px;">
          <span class="menu-status-tag" style="background:#1e1b4b; color:#a5b4fc; border:1px solid #6366f1;">📁 ${currentActiveProject}</span>
          <span class="menu-status-tag ${statusClass}">${statusLabel}</span>
        </div>
      </div>

      <div class="menu-options">
        <!-- Option 1: Save this address -->
        <button class="menu-item" id="opt-save-address">
          <span class="menu-item-icon">🌐</span>
          <div class="menu-item-content">
            <span class="menu-item-title">Save this address</span>
            <span class="menu-item-desc">Snapshot page URL, title & text into memory</span>
          </div>
        </button>

        <!-- Option 2: Stop reading / Resume reading -->
        <button class="menu-item" id="opt-toggle-reading">
          <span class="menu-item-icon">${pauseIcon}</span>
          <div class="menu-item-content">
            <span class="menu-item-title">${pauseToggleText}</span>
            <span class="menu-item-desc">${pauseToggleDesc}</span>
          </div>
        </button>

        <!-- Option 3: Write a new note -->
        <button class="menu-item" id="opt-write-note">
          <span class="menu-item-icon">📝</span>
          <div class="menu-item-content">
            <span class="menu-item-title">Write a new note</span>
            <span class="menu-item-desc">Quickly save a thought or key takeaway</span>
          </div>
        </button>

        <!-- Option 4: Switch or Create Project -->
        <button class="menu-item" id="opt-switch-project">
          <span class="menu-item-icon">📁</span>
          <div class="menu-item-content">
            <span class="menu-item-title">Project: ${currentActiveProject}</span>
            <span class="menu-item-desc">Click to switch or create project</span>
          </div>
        </button>
      </div>

      <div id="note-slot"></div>
    `;

    overlaySlot.appendChild(card);

    // Option 4 Handler: Switch or Create Project
    card.querySelector("#opt-switch-project").onclick = () => {
      const newProj = window.prompt("Enter new or existing project name (e.g. MySaaS, Billing, MobileApp):", currentActiveProject);
      if (newProj && newProj.trim()) {
        const cleanProj = newProj.trim();
        currentActiveProject = cleanProj;
        chrome.storage.local.get(["owl_projects_list"], (res) => {
          const list = res.owl_projects_list || ["General"];
          if (!list.includes(cleanProj)) list.push(cleanProj);
          chrome.storage.local.set({
            owl_active_project: cleanProj,
            owl_projects_list: list,
          });
        });
        showToast(`Active project: "${cleanProj}"`, "📁");
        renderActionMenu();
      }
    };

    // Option 1 Handler: Save this address
    card.querySelector("#opt-save-address").onclick = async () => {
      const extracted = extractVisiblePageText();
      const content = extracted.text || `Saved Page: ${pageTitle}\nURL: ${currentUrl}`;
      const payload = {
        text: `[Saved Page Bookmark]\nTitle: ${pageTitle}\nURL: ${currentUrl}\n\nContent Snippet:\n${content.slice(0, 2000)}`,
        type: "saved_address",
        metadata: { bookmark: true, url: currentUrl, title: pageTitle },
      };

      showToast("Saving page snapshot...", "⏳");
      const res = await syncCaptureToOwlThread(payload);
      if (res && res.success) {
        showToast("Address saved to OwlThread memory!", "🌐");
      } else if (res && res.queued) {
        showToast(`Queued (${res.queue_length} pending) — will sync when server is back`, "📦");
      } else {
        showToast("Failed saving address.", "❌");
      }
      closeMenu();
    };

    // Option 2 Handler: Stop reading / Resume reading
    card.querySelector("#opt-toggle-reading").onclick = () => {
      isReadingActive = !isReadingActive;
      updateBeaconStatus();
      if (isReadingActive) {
        showToast("Resumed ambient reading on this site", "🟢");
        performAmbientRead();
      } else {
        showToast("Stopped ambient reading on this site", "⏸️");
      }
      closeMenu();
    };

    // Option 3 Handler: Write a new note
    card.querySelector("#opt-write-note").onclick = () => {
      renderNoteComposer(card);
    };
  }

  let noteComposerDraft = "";

  function renderNoteComposer(card) {
    const noteSlot = card.querySelector("#note-slot");
    if (!noteSlot) return;

    noteSlot.innerHTML = `
      <div class="note-composer">
        <textarea class="note-textarea" id="owl-note-input" placeholder="Write your note or insight for ${hostname}...\n(Ctrl+Enter to save)"></textarea>
        <div class="note-actions">
          <span style="font-size: 10px; color: #64748b; margin-right: auto; align-self: center;">Ctrl+Enter to save</span>
          <button class="btn-cancel-note" id="btn-cancel-note">Cancel</button>
          <button class="btn-save-note" id="btn-save-note">Save Note</button>
        </div>
      </div>
    `;

    const inputEl = noteSlot.querySelector("#owl-note-input");
    inputEl.value = noteComposerDraft;
    inputEl.focus();

    inputEl.addEventListener("input", () => {
      noteComposerDraft = inputEl.value;
    });

    const submitNote = async () => {
      const noteText = inputEl.value.trim();
      if (!noteText) {
        showToast("Please write some note text first", "⚠️");
        return;
      }

      showToast("Saving note to OwlThread...", "⏳");
      const res = await syncCaptureToOwlThread({
        text: `[User Quick Note]\nNote: ${noteText}\nPage: ${pageTitle} (${currentUrl})`,
        type: "user_note",
        metadata: { note: noteText, url: currentUrl, title: pageTitle },
      });

      if (res && res.success) {
        noteComposerDraft = "";
        triggerNoteTakingAnimation("Note Saved", "Notes");
      } else if (res && res.queued) {
        noteComposerDraft = "";
        triggerNoteTakingAnimation("Note Queued", "Offline");
      } else {
        showToast("Error saving note.", "❌");
      }
      closeMenu();
    };

    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        submitNote();
      }
    });

    noteSlot.querySelector("#btn-cancel-note").onclick = () => {
      noteSlot.innerHTML = "";
    };

    noteSlot.querySelector("#btn-save-note").onclick = submitNote;
  }

  function toggleMenu() {
    if (isMenuOpen) {
      closeMenu();
    } else {
      isMenuOpen = true;
      renderActionMenu();
    }
  }

  function closeMenu() {
    isMenuOpen = false;
    overlaySlot.innerHTML = "";
  }

  // -------------------------------------------------------------
  // 9. Storage Management & 2-Way Desktop Coordination
  // -------------------------------------------------------------
  function saveSitePermission(status) {
    sitePermission = status;
    isReadingActive = status === "allowed";
    updateBeaconStatus();

    // 1. Save locally in chrome.storage
    if (chrome.runtime?.id) {
      try {
        chrome.storage.local.get(["owl_site_permissions"], (res) => {
          if (chrome.runtime?.lastError) return;
          const perms = res?.owl_site_permissions || {};
          perms[hostname] = status;
          chrome.storage.local.set({ owl_site_permissions: perms });
        });
      } catch (e) {}

      // 2. Synchronize with Desktop App backend
      try {
        chrome.runtime.sendMessage({
          action: "sync_site_permission",
          hostname: hostname,
          status: status,
        }, () => {
          if (chrome.runtime?.lastError) {}
        });
      } catch (e) {}
    }
  }

  function initializeSite() {
    restorePendingChunksFromStorage();
    setupOutputMutationObserver();

    // Sync initial active project
    if (chrome?.storage?.local) {
      try {
        chrome.storage.local.get(["owl_active_project"], (res) => {
          if (res && res.owl_active_project) {
            currentActiveProject = res.owl_active_project;
          }
        });
      } catch (e) {}
    }

    // Listen for real-time project & permission changes from Desktop App
    if (chrome.storage?.onChanged) {
      try {
        chrome.storage.onChanged.addListener((changes, area) => {
          if (area === "local") {
            if (changes.owl_active_project) {
              currentActiveProject = changes.owl_active_project.newValue || "General";
            }
            if (changes.owl_site_permissions) {
              const newPerms = changes.owl_site_permissions.newValue || {};
              const newStatus = newPerms[hostname];
              if (newStatus && newStatus !== sitePermission) {
                sitePermission = newStatus;
                isReadingActive = newStatus === "allowed";
                updateBeaconStatus();
              }
            }
          }
        });
      } catch (e) {}
    }

    // Check backend global pause state
    if (chrome.runtime?.id) {
      try {
        chrome.runtime.sendMessage({ action: "get_backend_state" }, (stateRes) => {
          if (chrome.runtime?.lastError) return;
          if (stateRes) {
            if (stateRes.is_paused) {
              isReadingActive = false;
              updateBeaconStatus();
            }
            if (stateRes.active_project) {
              currentActiveProject = stateRes.active_project;
            }
          }
        });
      } catch (e) {}
    }

    if (chrome?.runtime?.id && chrome?.storage?.local) {
      try {
        chrome.storage.local.get(["owl_site_permissions"], (res) => {
          if (chrome.runtime?.lastError) return;
          const perms = res?.owl_site_permissions || {};
          const perm = perms[hostname];

          if (perm === "allowed") {
            sitePermission = "allowed";
            isReadingActive = true;
            updateBeaconStatus();
            // Delay ambient read by 1.5s to allow dynamic SPA content to load
            setTimeout(performAmbientRead, 1500);
          } else if (perm === "blocked") {
            sitePermission = "blocked";
            isReadingActive = false;
            updateBeaconStatus();
          } else {
            // Check if known AI chat platform (ChatGPT, Claude, DeepSeek, Gemini, Perplexity)
            const isKnownAIChat = hostname.includes("chatgpt.com") ||
              hostname.includes("claude.ai") ||
              hostname.includes("deepseek.com") ||
              hostname.includes("perplexity.ai") ||
              hostname.includes("poe.com") ||
              hostname.includes("gemini.google.com");
            if (isKnownAIChat) {
              sitePermission = "allowed";
              isReadingActive = true;
              saveSitePermission("allowed");
              updateBeaconStatus();
              showToast(`🦉 OwlThread memory active for ${hostname}!`, "✨");
              setTimeout(performAmbientRead, 1500);
            } else {
              // First visit on standard site: show prompt
              sitePermission = "unknown";
              isReadingActive = false;
              updateBeaconStatus();
              setTimeout(renderPermissionPrompt, 1000);
            }
          }
        });
      } catch (e) {}
    }
  }

  // -------------------------------------------------------------
  // 10. Live Trigger Listeners (User Chat, AI Output, Highlight)
  // -------------------------------------------------------------

  // Trigger A: User sends a message via Enter key in chat / input boxes
  document.addEventListener(
    "keydown",
    (e) => {
      if (sitePermission !== "allowed" || !isReadingActive) return;
      if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        const target = e.target;
        if (!target) return;
        // Skip extension's own note composer or inside shadow host
        if (target.id === "owl-note-input" || hostElement.contains(target)) return;

        // Skip search fields, password inputs, or search forms
        if (target.type === "password" || target.type === "search" || target.getAttribute("role") === "searchbox") return;
        const form = target.closest("form");
        if (form && (form.getAttribute("role") === "search" || form.action?.includes("search"))) return;

        let userMsg = "";
        if (target.tagName === "TEXTAREA" || (target.tagName === "INPUT" && (target.type === "text" || !target.type))) {
          // If input element, only capture if in a chat/prompt context
          if (target.tagName === "INPUT") {
            const ph = (target.placeholder || "").toLowerCase();
            const isChatInput = ph.includes("message") ||
              ph.includes("prompt") ||
              ph.includes("ask") ||
              ph.includes("chat") ||
              target.id?.includes("prompt") ||
              hostname.includes("chatgpt") ||
              hostname.includes("claude") ||
              hostname.includes("deepseek") ||
              hostname.includes("copilot");
            if (!isChatInput) return;
          }
          userMsg = target.value;
        } else if (target.isContentEditable || target.getAttribute("contenteditable") === "true") {
          userMsg = target.innerText;
        }
        if (userMsg && userMsg.trim().length >= 4) {
          captureChunk(userMsg, "user_message", {
            trigger: "enter_key_submit",
            input_tag: target.tagName.toLowerCase(),
          });
        }
      }
    },
    true // Capture phase: grabs value right before forms or SPAs clear it
  );

  // Trigger B: User clicks a Send / Submit button
  document.addEventListener(
    "click",
    (e) => {
      if (sitePermission !== "allowed" || !isReadingActive) return;
      const btn = e.target.closest('button, [role="button"], input[type="submit"]');
      if (!btn) return;

      const btnText = (btn.innerText || btn.getAttribute("aria-label") || btn.getAttribute("title") || "").toLowerCase();
      const isSendBtn =
        btnText.includes("send") ||
        btnText.includes("submit") ||
        btn.getAttribute("data-testid")?.includes("send") ||
        btn.querySelector('svg[data-icon*="send"], svg.send-icon');

      if (isSendBtn) {
        let msg = "";
        const activeEl = document.activeElement;
        if (activeEl && (activeEl.tagName === "TEXTAREA" || activeEl.tagName === "INPUT" || activeEl.isContentEditable)) {
          msg = activeEl.value || activeEl.innerText;
        }
        if (!msg) {
          const form = btn.closest("form") || document;
          const field = form.querySelector("textarea, [contenteditable='true'], input[type='text']");
          if (field) msg = field.value || field.innerText;
        }
        if (msg && msg.trim().length >= 4) {
          captureChunk(msg, "user_message", { trigger: "send_button_click" });
        }
      }
    },
    true
  );

  // Trigger C: AI Output streaming completion (Mem0-style Resilient MutationObserver)
  let mutationSettledTimer = null;
  // -------------------------------------------------------------
  // ResilientStreamObserver (Manifest V3 Dual-Condition Observer)
  // -------------------------------------------------------------
  class ResilientStreamObserver {
    constructor(customDebounceMs = 1200) {
      this.debounceMs = customDebounceMs;
      this.heartbeatMs = 20000;
      this.portName = "owlthread-port";
      this.observer = null;
      this.debounceTimer = null;
      this.port = null;
      this.heartbeatTimer = null;
      this.reconnectTimer = null;
      this.reconnectAttempts = 0;
      this.isDestroyed = false;
      this.lastEmittedFingerprint = null;
      this.recentFingerprints = new Set();
      this.platform = this.detectPlatform();
    }

    detectPlatform() {
      const h = window.location.hostname.toLowerCase();
      if (h.includes("chatgpt.com") || h.includes("openai.com")) {
        return {
          id: "chatgpt",
          name: "ChatGPT",
          messageSelectors: [
            '[data-message-author-role="assistant"]',
            'article [data-message-author-role="assistant"]',
            'div.agent-turn [data-message-author-role="assistant"]',
          ],
          rootContainerSelectors: ["main", "div[role=\"presentation\"]", "body"],
          activeIndicators: [
            'button[data-testid="stop-button"]',
            'button[aria-label="Stop generating"]',
            'button[aria-label*="Stop"]',
          ],
        };
      }
      if (h.includes("claude.ai")) {
        return {
          id: "claude",
          name: "Claude",
          messageSelectors: [
            "div.font-claude-message",
            "[data-is-streaming]",
            'div[class*="font-claude-message"]',
            "div[data-test-render-count]",
          ],
          rootContainerSelectors: ["main", "div.flex-1.overflow-y-auto", "body"],
          activeIndicators: [
            'button[aria-label*="Stop"]',
            '[data-is-streaming="true"]',
            'button[data-testid="stop-button"]',
          ],
        };
      }
      if (h.includes("deepseek.com")) {
        return {
          id: "deepseek",
          name: "DeepSeek",
          messageSelectors: [
            "div.ds-markdown",
            'div[class*="ds-markdown"]',
            'div.chat-message[data-role="assistant"]',
          ],
          rootContainerSelectors: ["main", "div#root", "body"],
          activeIndicators: [
            ".ds-stop-button",
            '[aria-label*="Stop Generating"]',
            'button[aria-label*="Stop"]',
          ],
        };
      }
      return {
        id: "generic",
        name: "Generic Web AI",
        messageSelectors: [
          '[data-message-author-role="assistant"]',
          ".chat-message.ai-msg",
          'article[data-role="assistant"]',
          "article",
        ],
        rootContainerSelectors: ["main", "article", "div[role=\"main\"]", "body"],
        activeIndicators: [
          'button[data-testid="stop-button"]',
          'button[aria-label*="Stop"]',
        ],
      };
    }

    start() {
      if (this.isDestroyed) return;
      this.connectPort();
      this.attachObserver();
    }

    attachObserver() {
      let target = null;
      for (const sel of this.platform.rootContainerSelectors) {
        target = document.querySelector(sel);
        if (target) break;
      }
      if (!target) {
        target = document.body;
      }

      this.observer = new MutationObserver((mutations) => {
        const onlyExtension = mutations.every((m) => {
          const t = m.target;
          return t && (t.id === "owlthread-shadow-host" || (t.closest && t.closest("#owlthread-shadow-host")));
        });
        if (onlyExtension) return;

        if (this.debounceTimer !== null) {
          clearTimeout(this.debounceTimer);
        }
        this.debounceTimer = setTimeout(() => {
          this.debounceTimer = null;
          this.evaluateSettlement();
        }, this.debounceMs);
      });

      this.observer.observe(target, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }

    isGenerationActive() {
      for (const sel of this.platform.activeIndicators) {
        const els = document.querySelectorAll(sel);
        for (let i = 0; i < els.length; i++) {
          const el = els[i];
          if (el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0)) {
            return true;
          }
        }
      }
      return false;
    }

    evaluateSettlement() {
      if (this.isDestroyed) return;
      if (sitePermission !== "allowed" || !isReadingActive) return;

      if (this.isGenerationActive()) {
        this.debounceTimer = setTimeout(() => {
          this.debounceTimer = null;
          this.evaluateSettlement();
        }, this.debounceMs);
        return;
      }

      this.settleCompletedTurn();
    }

    settleCompletedTurn() {
      let nodes = [];
      for (const sel of this.platform.messageSelectors) {
        const found = document.querySelectorAll(sel);
        if (found.length > 0) {
          found.forEach((n) => {
            if (!nodes.some((ex) => ex.contains(n))) {
              nodes.push(n);
            }
          });
          break;
        }
      }
      if (!nodes.length) return;

      const lastNode = nodes[nodes.length - 1];
      const text = this.extractCleanText(lastNode);
      if (!text || text.length < 15) return;

      const fingerprint = this.computeFingerprint(text);
      if (this.recentFingerprints.has(fingerprint)) return;

      this.recentFingerprints.add(fingerprint);
      if (this.recentFingerprints.size > 50) {
        const oldest = this.recentFingerprints.values().next().value;
        this.recentFingerprints.delete(oldest);
      }
      this.lastEmittedFingerprint = fingerprint;

      // Animate living owl character while recording
      setOwlWritingState(true);
      setTimeout(() => setOwlWritingState(false), 1600);

      captureChunk(text, "assistant_response", {
        platform: this.platform.id,
        trigger: "stream_settled",
        fingerprint: fingerprint,
        turn_index: nodes.length,
      });
    }

    extractCleanText(rootNode) {
      if (!rootNode) return "";
      try {
        const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT, {
          acceptNode: (node) => {
            const parent = node.parentElement;
            if (!parent) return NodeFilter.FILTER_REJECT;
            const tag = parent.tagName.toUpperCase();
            if (["BUTTON", "SVG", "STYLE", "SCRIPT", "NOSCRIPT", "IFRAME", "CANVAS"].includes(tag)) {
              return NodeFilter.FILTER_REJECT;
            }
            if (parent.closest && parent.closest('[aria-hidden="true"]')) {
              return NodeFilter.FILTER_REJECT;
            }
            if (parent.closest && parent.closest("#owlthread-shadow-host")) {
              return NodeFilter.FILTER_REJECT;
            }
            if (!node.nodeValue || !node.nodeValue.trim()) {
              return NodeFilter.FILTER_SKIP;
            }
            return NodeFilter.FILTER_ACCEPT;
          },
        });

        const chunks = [];
        let curr = walker.nextNode();
        while (curr) {
          if (curr.nodeValue) chunks.push(curr.nodeValue);
          curr = walker.nextNode();
        }
        return chunks.join(" ").replace(/\s+/g, " ").trim();
      } catch (e) {
        return (rootNode.innerText || "").trim();
      }
    }

    computeFingerprint(text) {
      let hash = 0x811c9dc5;
      for (let i = 0; i < text.length; i++) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
      }
      return `fnv1a-${(hash >>> 0).toString(16).padStart(8, "0")}-len${text.length}`;
    }

    connectPort() {
      if (this.isDestroyed) return;
      try {
        if (this.port) {
          try { this.port.disconnect(); } catch (e) {}
          this.port = null;
        }
        this.port = chrome.runtime.connect({ name: this.portName });
        this.reconnectAttempts = 0;

        this.port.onDisconnect.addListener(() => {
          this.handlePortDisconnect();
        });

        this.startHeartbeat();
      } catch (err) {
        this.schedulePortReconnect();
      }
    }

    startHeartbeat() {
      if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = setInterval(() => {
        if (this.port) {
          try {
            this.port.postMessage({ type: "heartbeat", timestamp: Date.now() });
          } catch (e) {
            this.handlePortDisconnect();
          }
        }
      }, this.heartbeatMs);
    }

    handlePortDisconnect() {
      if (this.heartbeatTimer) {
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = null;
      }
      this.port = null;
      this.schedulePortReconnect();
    }

    schedulePortReconnect() {
      if (this.reconnectTimer !== null || this.isDestroyed) return;
      const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 10000);
      this.reconnectAttempts++;
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        if (!this.isDestroyed) this.connectPort();
      }, delay);
    }
  }

  let streamObserverInstance = null;

  function setupOutputMutationObserver() {
    if (!streamObserverInstance) {
      streamObserverInstance = new ResilientStreamObserver(1200);
      streamObserverInstance.start();
    }
  }

  // Trigger D: User text selection / highlight
  let selectionTimer = null;
  document.addEventListener("mouseup", () => {
    if (sitePermission !== "allowed" || !isReadingActive) return;
    const sel = window.getSelection();
    const selText = sel ? sel.toString().trim() : "";
    if (selText.length >= 20) {
      clearTimeout(selectionTimer);
      selectionTimer = setTimeout(() => {
        captureChunk(selText, "user_selection", { trigger: "highlight" });
      }, 500);
    }
  });

  // -------------------------------------------------------------
  // 11. Zero Data Loss Unload Handlers (Instant Tab Close Protection)
  // -------------------------------------------------------------
  window.addEventListener("beforeunload", () => {
    // Persist any un-synced chunks into local storage immediately
    persistActiveChunksQueue();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      persistActiveChunksQueue();
      drainChunksQueue();
    }
  });

  // -------------------------------------------------------------
  // 12. Draggable Floating Widget & Event Listeners
  // -------------------------------------------------------------
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let hasMoved = false;

  triggerBtn.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return; // Left mouse only
    isDragging = true;
    hasMoved = false;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    e.preventDefault();
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      hasMoved = true;
      const right = Math.max(12, Math.min(window.innerWidth - 68, window.innerWidth - e.clientX - 26));
      const bottom = Math.max(12, Math.min(window.innerHeight - 68, window.innerHeight - e.clientY - 26));
      hostElement.style.right = `${right}px`;
      hostElement.style.bottom = `${bottom}px`;

      // Auto-flip popover menu downwards if widget is in the top 45% of viewport
      if (e.clientY < window.innerHeight * 0.45) {
        container.setAttribute("data-flip", "top");
      } else {
        container.removeAttribute("data-flip");
      }
    }
  });

  window.addEventListener("mouseup", () => {
    isDragging = false;
  });

  triggerBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (hasMoved) return; // Ignore drag release clicks
    toggleMenu();
  });

  // Close menu on click outside (using composedPath to reliably pierce Shadow DOM boundary)
  document.addEventListener("click", (e) => {
    const path = e.composedPath ? e.composedPath() : [];
    if (isMenuOpen && !path.includes(hostElement)) {
      closeMenu();
    }
  });

  // Start initialization
  initializeSite();
})();
