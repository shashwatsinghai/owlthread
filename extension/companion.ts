/** The visual companion is isolated from both site styles and the passive AI observer. */
(() => {
  if (!/^https?:$/.test(location.protocol) || window.top !== window) return;
  if (OwlPolicy.hardBlocked(OwlPolicy.normalizeHost(location.hostname))) return;
  window.dispatchEvent(new Event("owlthread:dispose-companion"));
  document.getElementById("owlthread-companion")?.remove();

  const host = document.createElement("div");
  host.id = "owlthread-companion";
  host.style.cssText = "all:initial!important;position:fixed!important;inset:0!important;width:0!important;height:0!important;z-index:2147483647!important;pointer-events:none!important;color-scheme:dark!important;";
  const shadow = host.attachShadow({mode: "open"});
  shadow.innerHTML = `
    <style>
      :host{all:initial;color-scheme:dark;font-family:"Segoe UI",system-ui,sans-serif}
      *{box-sizing:border-box}button,input{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible{outline:2px solid #f3ce87;outline-offset:4px}
      [hidden]{display:none!important}.dock{position:fixed;width:112px;height:138px;pointer-events:none;color:#f3f2e9;font:13px/1.5 "Segoe UI",system-ui,sans-serif;isolation:isolate}
      .owl{position:relative;display:block;width:112px;height:112px;padding:0;border:0;background:transparent;pointer-events:auto;touch-action:none;user-select:none;cursor:grab;-webkit-tap-highlight-color:transparent}
      .owl:active{cursor:grabbing}.owl:focus-visible{border-radius:40%}
      .turn{position:relative;display:block;width:100%;height:100%;transform:perspective(500px) rotateY(var(--look-x,0deg)) rotateX(var(--look-y,0deg));transition:transform .32s ease-out}
      .bird{width:100%;height:100%;object-fit:contain;display:block;pointer-events:none;filter:drop-shadow(0 9px 7px #0005);transform-origin:50% 88%;animation:breathe 5.8s ease-in-out infinite}
      .perch{position:absolute;bottom:0;left:27px;width:58px;height:8px;border-radius:50%;background:#101a1b33;filter:blur(4px);z-index:-1;animation:shadow 5.8s ease-in-out infinite}
      .eyes{position:absolute;inset:0;pointer-events:none}.eye{position:absolute;top:25.3%;width:11.5%;height:10.5%;border-radius:50%;overflow:hidden}.eye.left{left:36.7%}.eye.right{right:36.7%}.pupil{position:absolute;left:50%;top:50%;width:44%;height:54%;border-radius:50%;background:#12110e;box-shadow:inset 1px 1px 1px #ffffff42;transform:translate(calc(-50% + var(--pupil-x,0px)),calc(-50% + var(--pupil-y,0px)));transition:transform .1s linear}.pupil:after{content:"";position:absolute;left:22%;top:14%;width:32%;height:27%;background:#fff9;border-radius:50%}
      .lid{position:absolute;top:24.2%;width:14.5%;height:12.8%;border-radius:52% 52% 48% 48%;background:linear-gradient(#8d755a,#bca180 65%,#715946);transform:scaleY(0);transform-origin:top;opacity:.98}.lid.left{left:35.2%}.lid.right{right:35.2%}.blinking .lid{animation:blink .19s ease-in-out}
      .activity{position:absolute;left:-11px;bottom:3px;width:47px;height:39px;opacity:0;transform:translateY(8px) scale(.8);transition:opacity .18s,transform .18s;pointer-events:none}.paper{position:absolute;left:1px;bottom:0;width:35px;height:29px;border-radius:3px;background:#fff9df;border:1px solid #d1b777;box-shadow:0 3px 7px #0003;transform:rotate(-6deg)}.paper:before{content:"";position:absolute;inset:7px 5px;background:repeating-linear-gradient(to bottom,#758a78 0 1px,transparent 1px 5px);opacity:.65}.pencil{position:absolute;right:1px;top:0;width:5px;height:28px;border-radius:3px 3px 1px 1px;background:linear-gradient(90deg,#9d5d37,#e8b35f 45%,#8d492c);transform:rotate(37deg);transform-origin:bottom}.done-mark{position:absolute;inset:2px 4px auto auto;display:grid;place-items:center;width:29px;height:29px;border-radius:50%;background:#e8cc8f;color:#183027;font:800 18px/1 "Segoe UI";box-shadow:0 4px 12px #0003;opacity:0;transform:scale(.4)}
      .state{pointer-events:auto;position:relative;display:flex;align-items:center;justify-content:center;gap:6px;margin:3px auto 0;padding:4px 8px;max-width:124px;width:max-content;min-height:23px;background:#132322f2;color:#deded2;border:1px solid #b8d1b32e;border-radius:20px;box-shadow:0 3px 12px #0002;font-size:9px;white-space:nowrap}
      .dot{display:inline-block;width:5px;height:5px;flex-shrink:0;border-radius:50%;background:#e6b967}.online .dot{background:#86d6b1}.paused .dot{background:#aeb6c0}
      .hint{position:absolute;bottom:148px;right:8px;width:192px;padding:10px 13px;border:1px solid #d2ddc730;border-radius:12px 12px 3px 12px;background:#132322f5;box-shadow:0 8px 30px #0002;color:#e6e6db;font-size:11px;opacity:0;transform:translateY(5px);transition:opacity .2s,transform .2s;pointer-events:none}
      .dock:not(.open):hover .hint,.dock:not(.open):focus-within .hint,.dock:not(.open).notice .hint{opacity:1;transform:translateY(0)}
      .panel{position:fixed;width:min(324px,calc(100vw - 24px));max-height:calc(100vh - 24px);overflow:auto;overscroll-behavior:contain;pointer-events:auto;background:linear-gradient(145deg,#203532,#112220 70%);border:1px solid #c4dbc52b;border-radius:20px;box-shadow:0 22px 70px #07151040,0 2px 8px #0002;color:#f3f2e9;animation:arrive .2s ease-out}
      .panel-head{display:flex;align-items:center;gap:8px;padding:20px 20px 14px}.mark{width:8px;height:8px;border:2px solid #e9bf75;transform:rotate(45deg);border-radius:2px}.brand{font-weight:650;font-size:14px;letter-spacing:-.2px}.version{font-size:9px;letter-spacing:1px;color:#a8bcb0;margin-left:4px}
      .icon-btn{display:grid;place-items:center;flex-shrink:0;width:28px;height:28px;padding:0;background:transparent;border:1px solid #c4dbc529;border-radius:8px;color:#bbcdc3;font-size:19px}.close{margin-left:auto}.icon-btn:hover{background:#ffffff0c}
      .intro{padding:0 20px}.eyebrow{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#dfbe83;margin:0 0 8px}.intro h2{font-family:Georgia,serif;font-size:27px;font-weight:400;letter-spacing:-.6px;line-height:1.15;margin:0 0 8px}.intro p{font-size:11px;color:#b6c9bc;margin:0;line-height:1.6}
      .awareness{display:flex;gap:8px;align-items:flex-start;margin:13px 20px 0;padding:10px 11px;border-radius:10px;background:#e9cc8b0b;border:1px solid #e9cc8b24;color:#cfdbd0;font-size:10px;line-height:1.45}.awareness-icon{color:#edcb8b}.awareness-text{overflow-wrap:anywhere}
      .connection{margin:17px 20px 0;border:1px solid #bfd9c325;border-radius:10px;padding:10px 11px;display:flex;align-items:center;gap:7px;font-size:11px;background:#0a191b35}.connection .count{margin-left:auto;font-size:10px;color:#b7c7bc}
      .actions{padding:14px 20px 0}.action{display:flex;align-items:center;justify-content:space-between;width:100%;padding:12px 13px;border-radius:10px;border:1px solid #c4dbc530;background:#ffffff05;color:#dbE8dc;font-size:11px;font-weight:550;transition:background .15s;margin:0 0 8px;text-align:left}.action:hover{background:#ffffff10}.action.primary{background:#eccb91;color:#1c2a22;border-color:#eccb91}.action.primary:hover{background:#f6dca9}.action:disabled{opacity:.55;cursor:wait}.arrow{font-size:16px}
      .setting{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 20px;color:#bdcdc2;font-size:11px}.setting input{accent-color:#e8c487;width:16px;height:16px;margin:0}.feedback{font-size:11px;line-height:1.55;color:#b3c7b9;margin:0;padding:0 20px 16px;min-height:46px;overflow-wrap:anywhere}.feedback.error{color:#f3b3a0}
      .panel-footer{display:flex;align-items:center;justify-content:space-between;padding:11px 20px;border-top:1px solid #bbd5bf1d;color:#8fa99b;font-size:9px}.text-btn{background:none;border:0;color:#c8d6cc;padding:3px;font-size:10px}.text-btn:hover{color:#edce93}
      .dragging .bird{animation:none;transform:rotate(-4deg) scale(1.04)}.dragging .hint{opacity:0!important}.dragging .turn{transition:none}.saving .activity{opacity:1;transform:translateY(0) scale(1)}.saving .bird{animation:write-posture .52s ease-in-out infinite alternate}.saving .pencil{animation:write-pencil .32s ease-in-out infinite alternate}.done .done-mark{animation:done-pop 1.45s ease-out}.done .bird{animation:done-hop 1.15s ease-out}.error-state .bird{animation:head-shake .38s ease-in-out}.curious:not(.saving):not(.done) .bird{animation:curious-posture .55s ease-out both}.sleeping *,.still *{animation:none!important;transition:none!important}.still .turn{transform:none}
      @keyframes breathe{0%,100%{transform:translateY(0) rotate(-.45deg) scaleY(1)}45%{transform:translateY(-3px) rotate(.55deg) scaleY(1.012)}70%{transform:translateY(-1px) rotate(.1deg)}}
      @keyframes blink{0%,100%{transform:scaleY(0)}48%,64%{transform:scaleY(1)}}
      @keyframes shadow{0%,100%{transform:scaleX(1);opacity:.8}45%{transform:scaleX(.88);opacity:.6}}
      @keyframes write-posture{from{transform:translate(-1px,1px) rotate(-2deg)}to{transform:translate(-3px,2px) rotate(-5deg)}}
      @keyframes write-pencil{from{transform:translate(-2px,1px) rotate(31deg)}to{transform:translate(3px,-1px) rotate(43deg)}}
      @keyframes done-pop{0%{opacity:0;transform:scale(.4) rotate(-18deg)}20%,75%{opacity:1;transform:scale(1) rotate(0)}100%{opacity:0;transform:scale(1.25)}}
      @keyframes done-hop{0%,100%{transform:translateY(0) rotate(0)}24%{transform:translateY(-9px) rotate(4deg)}48%{transform:translateY(-2px) rotate(-4deg)}70%{transform:translateY(-5px) rotate(2deg)}}
      @keyframes head-shake{0%,100%{transform:rotate(0)}25%{transform:rotate(-5deg)}75%{transform:rotate(5deg)}}
      @keyframes curious-posture{0%{transform:rotate(0)}55%,100%{transform:rotate(5deg) translateY(-2px)}}
      @keyframes arrive{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
      @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.turn{transform:none!important}}
      .dock{width:64px;height:84px}.owl{width:64px;height:64px}.perch{left:16px;width:33px;height:5px}
      .state{padding:3px 6px;min-height:18px;font-size:8px;max-width:100px}.state-text{max-width:75px;overflow:hidden;text-overflow:ellipsis}
      .hint{width:176px}.panel{width:min(300px,calc(100vw - 24px));border-radius:16px}
      .panel-head{padding:14px 16px 10px}.intro{padding:0 16px}.intro h2{font-size:23px}.intro p{font-size:11px}
      .awareness{margin:10px 16px 0}.connection{margin:10px 16px 0;flex-wrap:wrap}.connection-text{overflow-wrap:anywhere;min-width:0;flex:1}
      .actions{padding:10px 16px 0}.action{padding:10px 12px}.setting{padding:10px 16px}.feedback{padding:0 16px 12px}
      .panel-footer{padding:9px 16px}.activity{transform:translateY(8px) scale(.65);left:-19px;bottom:0}.saving .activity{transform:scale(.65)}
      .done-mark{width:22px;height:22px;font-size:14px}.understand{font-size:10px;padding:7px 16px;color:#e9cc8b;text-align:left}
      /* The plush, eyes and props share one moving body, so every pose stays aligned. */
      .bird{position:relative;filter:drop-shadow(0 3px 3px #17251b38);animation:cozy-breathe 5.6s ease-in-out infinite}
      .plush{display:block;width:100%;height:100%;object-fit:contain;pointer-events:none}
      .eye{top:31.4%;width:17.4%;height:17.2%;background:radial-gradient(ellipse at 55% 65%,#fff7df 32%,#f6dfb6 100%);box-shadow:inset 0 .6px 1px #6c3d215c;border-radius:50%}
      .eye.left{left:28.6%}.eye.right{left:54%;right:auto}
      .pupil{width:78%;height:84%;background:radial-gradient(ellipse at 50% 43%,#21150e 0 51%,#7a420e 54%,#d7972c 72%,#f9d47c 88%,#965b18 100%);box-shadow:inset 0 0 .7px #522f19;transition:transform .16s ease-out}
      .pupil:after{left:23%;top:14%;width:24%;height:22%;background:#fffdf4;box-shadow:2px 3px 0 -1px #fffa}
      .lid{inset:0;width:100%;height:100%;border-radius:45% 45% 50% 50%;background:linear-gradient(#eccda0,#f7e6ca 75%,#b78452);border-bottom:.7px solid #98633c;opacity:1;transform:scaleY(0);transform-origin:50% 0;transition:transform .5s ease}
      .blinking .lid{animation:cozy-blink .2s ease-in-out}.double-blink .lid{animation:cozy-double-blink .48s ease-in-out}
      .dozing .lid{transform:scaleY(.6)}.dozing .bird{animation-duration:8s}.still .pupil{transform:translate(-50%,-50%)}
      .activity{inset:auto 5% 1% 5%;width:90%;height:48%;transform:translateY(10px) rotate(14deg) scale(.35);transform-origin:50% 100%;transition:transform .32s cubic-bezier(.2,.8,.2,1),opacity .18s}
      .notebook{display:block;width:100%;height:100%;overflow:visible;filter:drop-shadow(0 2px 2px #30231855)}
      .book-pages{transform-origin:36px 42px}.writing-hand{position:absolute;right:2%;top:-32%;width:38%;height:112%;transform-origin:45% 92%}
      .writing-hand svg{display:block;width:100%;height:100%;overflow:visible}.ink-line{stroke-dasharray:19;stroke-dashoffset:19}
      .saving .activity{opacity:1;transform:translateY(0) rotate(-5deg) scale(1)}.saving .book-pages{animation:book-open .4s ease-out both}
      .saving .bird{animation:cozy-write .7s ease-in-out infinite alternate}.saving .writing-hand{animation:pencil-scribble .85s linear infinite}
      .saving .ink-line{animation:ink-appear 1.7s linear infinite}.saving .ink-line:nth-of-type(2){animation-delay:.35s}.saving .ink-line:nth-of-type(3){animation-delay:.7s}
      .saving .pupil{transform:translate(calc(-50% + .9px),calc(-50% + 1.6px))}
      .magnifier{position:absolute;left:55%;top:28%;width:47%;height:66%;opacity:0;transform:translateY(14px) rotate(25deg) scale(.35);transform-origin:65% 85%;transition:opacity .2s,transform .3s cubic-bezier(.2,.8,.2,1);pointer-events:none}
      .magnifier svg{display:block;width:100%;height:100%;overflow:visible;filter:drop-shadow(0 1px 1px #30231855)}
      .inspecting .magnifier{opacity:1;transform:translateY(0) rotate(-8deg) scale(1)}.inspecting .magnifier svg{animation:glass-search 1.8s ease-in-out infinite}
      .inspecting .bird{animation:cozy-inspect 1.8s ease-in-out infinite}.inspecting .lens-shine{animation:lens-shine 1.8s ease-in-out infinite}
      .inspecting .pupil{transform:translate(calc(-50% + 1px),calc(-50% - .2px))}
      .spark{position:absolute;width:7px;height:10px;background:#f7d59c;clip-path:polygon(50% 0,63% 36%,100% 50%,63% 63%,50% 100%,36% 63%,0 50%,36% 36%);opacity:0;pointer-events:none}
      .spark.one{left:2%;top:20%}.spark.two{right:0;top:7%;width:5px;height:7px}.done .spark{animation:cozy-spark 1.25s ease-out}.done .spark.two{animation-delay:.12s}
      .done .bird{animation:cozy-happy 1.2s ease-out}.done .done-mark{animation:done-pop 1.6s ease-out}.done-mark{width:17px;height:17px;font-size:11px;right:-3px;top:1px;background:#dceaba;box-shadow:0 2px 6px #20362333}
      .curious:not(.saving):not(.done) .bird{animation:cozy-hello .9s ease-in-out}.dragging .bird{animation:none;transform:rotate(-5deg) scale(1.04)}
      .still.done .done-mark{opacity:1;transform:scale(1)}.still .ink-line{stroke-dashoffset:0}.still .lid{transform:scaleY(0)}.still .pupil{transform:translate(-50%,-50%)!important}
      @keyframes cozy-breathe{0%,100%{transform:translateY(0) scaleY(1)}50%{transform:translateY(-1.1px) scaleY(1.014)}}
      @keyframes cozy-blink{0%,100%{transform:scaleY(0)}40%,65%{transform:scaleY(1)}}
      @keyframes cozy-double-blink{0%,42%,55%,100%{transform:scaleY(0)}17%,29%,72%,84%{transform:scaleY(1)}}
      @keyframes book-open{from{transform:scaleY(.15) skewX(-12deg)}to{transform:scaleY(1) skewX(0)}}
      @keyframes cozy-write{from{transform:translateY(1px) rotate(-2deg)}to{transform:translateY(1.7px) rotate(-4deg)}}
      @keyframes pencil-scribble{0%{transform:translate(-2px,-1px) rotate(-13deg)}15%{transform:translate(1px,0) rotate(-4deg)}30%{transform:translate(-1px,1px) rotate(-10deg)}48%{transform:translate(2px,1.5px) rotate(0)}65%{transform:translate(0,2px) rotate(-9deg)}85%{transform:translate(2px,3px) rotate(-2deg)}100%{transform:translate(-2px,-1px) rotate(-13deg)}}
      @keyframes ink-appear{0%,10%{stroke-dashoffset:19}55%,90%{stroke-dashoffset:0}100%{stroke-dashoffset:19}}
      @keyframes glass-search{0%,100%{transform:translate(-1px,0) rotate(-5deg)}50%{transform:translate(1.5px,-1px) rotate(5deg)}}
      @keyframes cozy-inspect{0%,100%{transform:rotate(1deg)}50%{transform:rotate(-3deg) translateY(-.8px)}}
      @keyframes lens-shine{0%,100%{opacity:.4}50%{opacity:.95}}
      @keyframes cozy-spark{0%,100%{opacity:0;transform:scale(.3) translateY(3px)}25%,65%{opacity:1;transform:scale(1) translateY(-3px)}}
      @keyframes cozy-happy{0%,100%{transform:translateY(0) rotate(0)}25%{transform:translateY(-4px) rotate(3deg)}50%{transform:translateY(0) rotate(-3deg)}75%{transform:translateY(-1.5px) rotate(1deg)}}
      @keyframes cozy-hello{0%,100%{transform:rotate(0)}40%,65%{transform:rotate(6deg) translateY(-1px)}}
      @media(prefers-reduced-motion:reduce){.pupil{transform:translate(-50%,-50%)!important}.lid{transform:scaleY(0)!important}.done .done-mark{opacity:1;transform:scale(1)}.ink-line{stroke-dashoffset:0}}
    </style>
    <div class="dock" hidden>
      <div class="hint" role="status" aria-live="polite">Your little memory keeper.<br>Click to open · Drag to move</div>
      <button class="owl" aria-label="Open OwlThread companion. Drag or use arrow keys to move." aria-expanded="false" aria-controls="owl-panel">
        <span class="perch" aria-hidden="true"></span><span class="turn"><span class="bird">
          <img class="plush" alt="Cozy little developer owl in a green hoodie with code-bracket ears" draggable="false">
          <span class="eyes" aria-hidden="true"><span class="eye left"><i class="pupil"></i><i class="lid"></i></span><span class="eye right"><i class="pupil"></i><i class="lid"></i></span></span>
          <span class="activity" aria-hidden="true">
            <svg class="notebook" viewBox="0 0 72 44" fill="none"><path d="M3 8Q17 3 35 8Q52 3 69 8V41Q52 36 36 42Q19 36 3 41Z" fill="#735744" stroke="#473d31" stroke-width="1.3"/>
              <g class="book-pages"><path d="M5 5Q20 1 35 7V39Q19 33 5 38Z" fill="#fff1cf"/><path d="M35 7Q51 1 67 5V38Q50 33 35 39Z" fill="#fff8e2"/><path d="M35 8V38" stroke="#d7bd90" stroke-width="1.3"/><path d="M12 14H27M12 19H27M12 24H24" stroke="#cdbf9a" stroke-width="1.1" stroke-linecap="round"/><path d="m16 29-4 3 4 3m9-6 4 3-4 3m-3-7-3 8" stroke="#658475" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><g stroke="#617f6a" stroke-width="1.4" stroke-linecap="round"><path class="ink-line" d="M42 15h17"/><path class="ink-line" d="M42 21h15"/><path class="ink-line" d="M42 27h18"/></g></g>
            </svg>
            <span class="writing-hand"><svg viewBox="0 0 32 42" fill="none"><path d="m17 6 6-3 8 26-5 8Z" fill="#ecbd61" stroke="#9a6d38" stroke-width="1.1"/><path d="m17 6 6-3 2 6-6 2Z" fill="#dc9b8c"/><path d="m26 37 5-8-2 9-3 3Z" fill="#f7dfb4"/><path d="m26 39 3-1-3 3Z" fill="#3c3b31"/><path d="M7 18Q13 11 21 18L26 26Q27 31 22 33Q16 34 12 29L5 24Z" fill="#ca914f" stroke="#a06c39" stroke-width="1"/><path d="m14 22 6 6m-8-2 5 5" stroke="#e6b772" stroke-width="1.5" stroke-linecap="round"/></svg></span>
          </span>
          <span class="magnifier" aria-hidden="true"><svg viewBox="0 0 42 62" fill="none"><path d="m24 29 11 24" stroke="#704d33" stroke-width="8" stroke-linecap="round"/><path d="m24 29 11 24" stroke="#bd8850" stroke-width="4.5" stroke-linecap="round"/><circle cx="18" cy="18" r="14.5" fill="#c9eee42b" stroke="#5b4a35" stroke-width="4.5"/><circle cx="18" cy="18" r="14.5" stroke="#e9c788" stroke-width="2.4"/><path class="lens-shine" d="M8 18a10 10 0 0 1 10-10m7 16 2-3" stroke="#fff9e4" stroke-width="2.3" stroke-linecap="round"/><path d="M26 40Q31 34 36 40L39 47Q40 52 35 54Q31 56 28 51L24 46Q22 42 26 40Z" fill="#d29b5a" stroke="#a5713e" stroke-width="1.1"/><path d="m29 43 5 6m-7-2 4 5" stroke="#ebbd7f" stroke-linecap="round"/></svg></span>
        </span></span><span class="done-mark" aria-hidden="true">✓</span><span class="spark one" aria-hidden="true"></span><span class="spark two" aria-hidden="true"></span>
      </button>
      <button class="state" aria-label="Open OwlThread status"><span class="dot"></span><span class="state-text">Ready to capture</span></button>
      <section class="panel" id="owl-panel" role="dialog" aria-label="OwlThread memory companion" hidden>
        <div class="panel-head"><span class="mark"></span><span class="brand">OwlThread</span><span class="version">COMPANION</span><button class="icon-btn close" aria-label="Close companion panel">×</button></div>
        <div class="intro"><div class="eyebrow">A little wiser, together</div><h2>Just the useful bits.</h2><p class="site-copy">Remember the current AI turn or this page.<br>No text selection needed.</p></div><div class="awareness"><span class="awareness-icon">◉</span><span class="awareness-text">Page text stays here until you ask for understanding or press Remember.</span></div><button class="text-btn understand">Understand this page ↗</button>
        <div class="connection"><span class="dot"></span><span class="connection-text">Browser ready</span><span class="count">0 queued</span></div>
        <div class="actions"><button class="action primary capture"><span>Remember current turn / page</span><span class="arrow">↗</span></button><button class="action extract"><span>Extract saved memories</span><span class="arrow">✧</span></button></div>
        <label class="setting"><span>Filter new AI replies for memory</span><input class="auto" type="checkbox" checked></label>
        <p class="feedback" role="status" aria-live="polite">Saved on this device. You're in control.</p>
        <div class="panel-footer"><span>SAVED TO OWLTHREAD</span><button class="text-btn hide">Never on this site</button></div>
      </section>
    </div>`;
  const get = <T extends HTMLElement>(selector: string): T => shadow.querySelector<T>(selector)!;
  const dock = get<HTMLDivElement>(".dock");
  const owl = get<HTMLButtonElement>(".owl");
  const panel = get<HTMLElement>(".panel");
  const feedback = get<HTMLParagraphElement>(".feedback");
  const auto = get<HTMLInputElement>(".auto");
  get<HTMLImageElement>(".plush").src = chrome.runtime.getURL("assets/owl-cozy-developer.png");
  document.documentElement.append(host);

  const hostname = OwlPolicy.host(location.href);
  const aiSite = OwlPolicy.aiSites.includes(hostname);
  const youtube = location.hostname === "youtube.com" || location.hostname.endsWith(".youtube.com") || location.hostname === "youtu.be";
  if (aiSite) {
    get(".site-copy").textContent = "I check completed AI responses for durable context. You can also choose text yourself.";
    get(".capture span").textContent = "Remember current turn / page";
  } else if (youtube) {
    get(".site-copy").textContent = "You invited me here. Save the current turn or page without selecting text.";
  }
  if (!aiSite) get(".setting").hidden = true;
  let disposed = false, enabled = true, visible = true, motion = true, settingsVersion = 0;
  let siteAllowed = false;
  let settingsLoaded = false;
  const changedSettings = new Set<string>();
  let siteSettings: Record<string, unknown> = {};
  let x = Math.max(12, innerWidth - 84), y = Math.max(12, innerHeight - 108);
  let queued = 0, connected = false, modelLabel = "", busy = false, dragged = false;
  let awareUrl = "", awareAt = 0;
  let awareFingerprint = "";
  let awarenessVersion = 0;
  let awarenessBusy = false;
  type Activity = "saving" | "inspecting" | "done" | "error-state" | "curious" | "";
  let currentActivity: Activity = "";
  let drag: {id: number; sx: number; sy: number; x: number; y: number} | undefined;
  let hintTimer: ReturnType<typeof setTimeout> | undefined, activityTimer: ReturnType<typeof setTimeout> | undefined;
  const disposers: Array<() => void> = [];
  function listen(target: EventTarget, type: string, fn: EventListener, options?: AddEventListenerOptions): void {
    target.addEventListener(type, fn, options);
    disposers.push(() => target.removeEventListener(type, fn, options));
  }
  function position(): void {
    x = Math.min(Math.max(12, x), Math.max(12, innerWidth - 76));
    y = Math.min(Math.max(12, y), Math.max(12, innerHeight - 96));
    dock.style.left = x + "px"; dock.style.top = y + "px";
    if (!panel.hidden) {
      const w = panel.offsetWidth || Math.min(300, innerWidth - 24);
      const h = panel.offsetHeight || 430;
      const left = x >= w + 20 ? x - w - 12 : x + 76;
      panel.style.left = Math.max(12, Math.min(left, innerWidth - w - 12)) + "px";
      panel.style.top = Math.max(12, Math.min(y - h + 84, innerHeight - h - 12)) + "px";
    }
    const hint = get(".hint");
    hint.style.right = x < 80 ? "auto" : "8px";
    hint.style.left = x < 80 ? "0" : "auto";
    hint.style.bottom = y < 110 ? "auto" : "94px";
    hint.style.top = y < 110 ? "94px" : "auto";
  }
  function notice(text: string, error = false): void {
    feedback.textContent = text;
    feedback.classList.toggle("error", error);
  }
  async function send(message: unknown): Promise<any> {
    try {
      if (!chrome.runtime.id) throw new Error("Extension reloaded");
      const reply = await chrome.runtime.sendMessage(message);
      return reply || {ok: false, error: "No reply. Reload this tab and try again."};
    } catch {
      return {ok: false, error: "Extension updated. Refresh this tab to reconnect your owl."};
    }
  }
  async function save(values: Record<string, unknown>): Promise<void> {
    try { await OwlPolicy.save(values); }
    catch { notice("Refresh this tab to reconnect your owl.", true); }
  }
  function renderStatus(): void {
    auto.checked = enabled;
    dock.hidden = !settingsLoaded || !visible || !siteAllowed || !!document.fullscreenElement;
    dock.classList.toggle("still", !motion);
    dock.classList.toggle("online", connected);
    dock.classList.toggle("paused", !enabled);
    get(".state-text").textContent = currentActivity === "saving" ? "Taking notes…" : currentActivity === "inspecting" ? "Looking closer…" :
      currentActivity === "done" ? "Noted ✓" : queued ? `${queued} queued` : !enabled && aiSite ? "Auto-save paused" : connected ? "Memory connected" : "Ready to capture";
    get(".connection-text").textContent = connected ? modelLabel || "Desktop connected" : "Desktop offline";
    get(".count").textContent = `${queued} queued`;
  }
  async function checkHealth(): Promise<void> {
    const health = await send({type: "health"});
    if (disposed) return;
    connected = health.ok === true;
    modelLabel = health.model_ready && health.model_name ? health.model_name : "";
    renderStatus();
    if (!busy && !feedback.dataset.action) notice(connected ? "Captures sync to OwlThread. A model is optional for later synthesis." : "Desktop offline. Captures remain safely queued in this browser.");
  }
  function activity(state: Activity): void {
    clearTimeout(activityTimer);
    currentActivity = state;
    dock.dataset.activity = state || "idle";
    dock.classList.remove("saving","inspecting","done","error-state","curious","dozing");
    if (state) dock.classList.add(state);
    renderStatus();
    if (state && state !== "saving" && state !== "inspecting") activityTimer = setTimeout(() => activity(""), state === "done" ? 1650 : 950);
  }
  async function finishVisiblePose(started: number): Promise<void> {
    // Send immediately; only the visual completion waits long enough for a short
    // notebook/glass gesture to read. Reduced-motion users see no added delay.
    if (!motion || reduced.matches) return;
    const remaining = 1100 - (performance.now() - started);
    if (remaining > 0) await new Promise<void>(resolve => setTimeout(resolve, remaining));
  }
  async function understandPage(): Promise<void> {
    if (!siteAllowed || awarenessBusy || busy) return;
    const selection = OwlPolicy.pageSelection();
    const visibleText = OwlPolicy.pageText();
    const fingerprint=location.href+"\0"+document.title+"\0"+selection+"\0"+visibleText;
    if (awareFingerprint === fingerprint && Date.now() - awareAt < 90000) return;
    const version = ++awarenessVersion;
    const url = location.href;
    awarenessBusy = true;
    const started = performance.now();
    activity("inspecting");
    get<HTMLButtonElement>(".understand").disabled = true;
    const awareness = get(".awareness-text");
    awareness.textContent = "Asking your desktop model about this page…";
    const result = await send({type: "page_context", payload: {url, title: document.title,
      selection: selection.slice(0,4000), visible_text: visibleText}});
    await finishVisiblePose(started);
    if (disposed) return;
    awarenessBusy = false;
    get<HTMLButtonElement>(".understand").disabled = false;
    if (currentActivity === "inspecting") activity("");
    if (disposed || panel.hidden || version !== awarenessVersion || location.href !== url) return;
    if (result.ok) {
      awareUrl = url; awareAt = Date.now();
      awareFingerprint=fingerprint;
      awareness.textContent = result.summary + (result.intelligence === "model" ? ` · ${result.model || "AI"}` : " · local view");
      if (!busy) activity("curious");
    } else awareness.textContent = "I know this page's URL and title. Connect the desktop for AI page understanding.";
  }
  function setOpen(open: boolean): void {
    if (open && (!siteAllowed || !visible)) return;
    if (!open) {
      awarenessVersion++;
      if (currentActivity === "inspecting") activity("");
    }
    panel.hidden = !open;
    dock.classList.toggle("open", open);
    owl.setAttribute("aria-expanded", String(open));
    position();
    if (open) {
      if (!busy && !awarenessBusy) activity("curious");
      get<HTMLButtonElement>(".close").focus({preventScroll: true});
      void checkHealth();
      if (awareUrl !== location.href) get(".awareness-text").textContent = "Page text stays here until you ask for understanding or press Remember.";
    }
  }
  function onSettings(changes: {[key: string]: chrome.storage.StorageChange}, area: string): void {
    if (area !== "local") return;
    settingsVersion++;
    for (const [key, change] of Object.entries(changes)) {
      changedSettings.add(key);
      if (change.newValue === undefined) delete siteSettings[key]; else siteSettings[key] = change.newValue;
    }
    siteAllowed = OwlPolicy.allowed(siteSettings, hostname);
    if (!siteAllowed) setOpen(false);
    if (changes.enabled) enabled = changes.enabled.newValue !== false;
    if (changes.companionVisible) { visible = changes.companionVisible.newValue !== false; if (!visible) setOpen(false); }
    if (changes.companionMotion) motion = changes.companionMotion.newValue !== false;
    if (changes.outbox) queued = Array.isArray(changes.outbox.newValue) ? changes.outbox.newValue.length : 0;
    renderStatus();
  }
  const initialVersion = settingsVersion;
  void OwlPolicy.settings().then(settings => {
    if (disposed) return;
    for (const [key, value] of Object.entries(settings)) { if (!changedSettings.has(key)) siteSettings[key] = value; }
    settingsLoaded = true;
    siteAllowed = OwlPolicy.allowed(siteSettings, hostname);
    if (initialVersion === settingsVersion) {
      enabled = settings.enabled !== false; visible = settings.companionVisible !== false; motion = settings.companionMotion !== false;
      queued = Array.isArray(settings.outbox) ? settings.outbox.length : 0;
    }
    const p = settings.companionPosition as {x?: unknown; y?: unknown} | null;
    if (p && typeof p.x === "number" && typeof p.y === "number" && Number.isFinite(p.x) && Number.isFinite(p.y)) { x = p.x; y = p.y; }
    enabled = siteSettings.enabled !== false; visible = siteSettings.companionVisible !== false; motion = siteSettings.companionMotion !== false;
    queued = Array.isArray(siteSettings.outbox) ? siteSettings.outbox.length : 0;
    renderStatus(); position();
  }).catch(() => { dock.hidden = true; });
  OwlPolicy.onChange(onSettings);

  listen(document, "pointerdown", event => {
    if (!event.composedPath().includes(host)) {
      if (!panel.hidden) setOpen(false);
    }
  }, {capture: true});
  listen(owl, "pointerdown", event => {
    const e = event as PointerEvent;
    if (e.button !== 0) return;
    drag = {id: e.pointerId, sx: e.clientX, sy: e.clientY, x, y}; dragged = false;
    owl.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  listen(owl, "pointermove", event => {
    const e = event as PointerEvent;
    if (!drag || drag.id !== e.pointerId) return;
    if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 5) dragged = true;
    if (!dragged) return;
    dock.classList.add("dragging");
    x = drag.x + e.clientX - drag.sx; y = drag.y + e.clientY - drag.sy; position();
  });
  const finishDrag = (): void => {
    if (!drag) return;
    if (owl.hasPointerCapture(drag.id)) owl.releasePointerCapture(drag.id);
    drag = undefined; dock.classList.remove("dragging");
    if (dragged) void save({companionPosition: {x, y}});
  };
  listen(owl, "pointerup", finishDrag); listen(owl, "pointercancel", finishDrag);
  listen(owl, "click", () => { if (!dragged) setOpen(panel.hidden); dragged = false; });
  listen(get(".state"), "click", () => setOpen(panel.hidden));
  listen(get(".close"), "click", () => { setOpen(false); owl.focus({preventScroll: true}); });
  listen(get(".hide"), "click", async () => {
    try {
      await OwlPolicy.save({[OwlPolicy.key(hostname)]: "blocked"});
      siteAllowed = false; setOpen(false); renderStatus();
    } catch { notice("Could not remember your site choice. Please try again.", true); }
  });
  listen(get(".understand"), "click", () => { void understandPage(); });
  listen(auto, "change", () => { enabled = auto.checked; renderStatus(); void save({enabled}); });
  listen(shadow, "keydown", event => {
    const e = event as KeyboardEvent;
    if (e.key === "Escape") { setOpen(false); owl.focus({preventScroll: true}); e.preventDefault(); }
    if (e.target !== owl || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault(); const step = e.shiftKey ? 40 : 12;
    x += e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
    y += e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
    position(); void save({companionPosition: {x, y}});
  });
  for (const [selector, type] of [[".capture", "capture_tab"], [".extract", "flush"]]) {
    listen(get(selector), "click", async () => {
      if (busy) return;
      busy = true;
      const started = performance.now();
      feedback.dataset.action = "true";
      activity("saving");
      shadow.querySelectorAll<HTMLButtonElement>(".action").forEach(button => { button.disabled = true; });
      notice(type === "flush" ? "Turning your saved captures into memories…" : "Saving to this device…");
      const result = await send({type});
      await finishVisiblePose(started);
      if (disposed) return;
      if (result.ok) {
        const count = result.total_extracted ?? 0;
        const text = type === "flush" ? `Extracted ${count} ${count === 1 ? "memory" : "memories"}.${result.errors?.length ? " Some captures need another try." : ""}` : "Remembered. Saved here for sync to OwlThread.";
        notice(text); get(".hint").textContent = text; dock.classList.add("notice");
        clearTimeout(hintTimer); hintTimer = setTimeout(() => dock.classList.remove("notice"), 3500);
        activity("done");
      } else { notice(result.error || "Could not save. Please try again.", true); activity("error-state"); }
      busy = false;
      shadow.querySelectorAll<HTMLButtonElement>(".action").forEach(button => { button.disabled = false; });
    });
  }
  let lastLook = 0;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let lastInteraction = Date.now(), lastGreeting = 0;
  function wake(): void { lastInteraction = Date.now(); dock.classList.remove("dozing"); }
  listen(owl, "pointerenter", () => {
    wake();
    if (motion && !reduced.matches && !currentActivity && Date.now() - lastGreeting > 12000) {
      lastGreeting = Date.now(); activity("curious");
    }
  });
  listen(owl, "focus", wake);
  listen(document, "pointermove", event => {
    if (document.hidden || dock.hidden) return;
    wake();
    if (!motion || reduced.matches || drag || Date.now() - lastLook < 45) return;
    lastLook = Date.now(); const e = event as PointerEvent;
    const dx = e.clientX - x - 32, dy = e.clientY - y - 24;
    dock.style.setProperty("--look-x", Math.max(-3.5, Math.min(3.5, dx / 130)) + "deg");
    dock.style.setProperty("--look-y", Math.max(-2, Math.min(2, -dy / 180)) + "deg");
    const distance = Math.max(120, Math.hypot(dx,dy));
    dock.style.setProperty("--pupil-x", (dx / distance * 1.65).toFixed(2) + "px");
    dock.style.setProperty("--pupil-y", (dy / distance * 1.25).toFixed(2) + "px");
  }, {passive: true});
  listen(document, "keydown", wake, {passive: true});
  listen(document, "pointerleave", () => {
    for (const key of ["--pupil-x","--pupil-y"]) dock.style.setProperty(key,"0px");
    for (const key of ["--look-x","--look-y"]) dock.style.setProperty(key,"0deg");
  });
  listen(document, "visibilitychange", () => dock.classList.toggle("sleeping", document.hidden));
  listen(document, "fullscreenchange", () => { if (document.fullscreenElement) setOpen(false); renderStatus(); });
  listen(window, "resize", position, {passive: true});
  let blinkTimer: ReturnType<typeof setTimeout> | undefined;
  let blinkEndTimer: ReturnType<typeof setTimeout> | undefined;
  function scheduleBlink(): void {
    clearTimeout(blinkTimer);
    blinkTimer = setTimeout(() => {
      if (!document.hidden && !dock.hidden && motion && !reduced.matches && !currentActivity) {
        const blink = Math.random() < .22 ? "double-blink" : "blinking";
        dock.classList.add(blink);
        clearTimeout(blinkEndTimer);
        blinkEndTimer = setTimeout(() => dock.classList.remove(blink), blink === "double-blink" ? 510 : 230);
        dock.classList.toggle("dozing", panel.hidden && Date.now() - lastInteraction > 30000);
      }
      scheduleBlink();
    },2800+Math.random()*3900);
  }
  scheduleBlink();
  const healthTimer = setInterval(() => { if (!document.hidden && !panel.hidden && !busy) void checkHealth(); }, 30000);
  function dispose(): void {
    if (disposed) return;
    disposed = true; clearInterval(healthTimer); clearTimeout(hintTimer); clearTimeout(activityTimer); clearTimeout(blinkTimer); clearTimeout(blinkEndTimer);
    OwlPolicy.removeChange(onSettings);
    disposers.forEach(remove => remove()); host.remove();
  }
  listen(window, "owlthread:dispose-companion", dispose, {once: true});
  position();
})();
