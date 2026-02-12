var I=Object.defineProperty;var _=(t,a,e)=>a in t?I(t,a,{enumerable:!0,configurable:!0,writable:!0,value:e}):t[a]=e;var i=(t,a,e)=>_(t,typeof a!="symbol"?a+"":a,e);let d=null,h=null,m=null,f=0;const C=200,D="200px 0px",w="data-load-mode",x="click",P="Load player",O="Loading player...",B="Try again",S="Unable to load the audio player. Please try again.",b="data-podlove-embed",g="data-podlove-embed-loaded",y="data-podlove-embed-failed",E="podlove-player-styles",L="color_scheme",p="#1e293b",u="#ffffff";function M(){return document.readyState==="complete"?Promise.resolve():(h||(h=new Promise(t=>{window.addEventListener("load",()=>t(),{once:!0})})),h)}function R(){return m||(m=new IntersectionObserver((t,a)=>{t.forEach(e=>{if(!e.isIntersecting)return;const r=e.target;r instanceof k&&r.scheduleInitialize(),a.unobserve(r)})},{rootMargin:D})),m}function H(t){return typeof podlovePlayer=="function"?Promise.resolve():d||(d=new Promise((a,e)=>{const r=document.querySelector(`script[${b}]`);if(r){if(r.getAttribute(g)==="true"&&typeof podlovePlayer=="function"){a();return}if(r.getAttribute(y)==="true")r.remove();else{r.addEventListener("load",()=>a(),{once:!0}),r.addEventListener("error",()=>{r.setAttribute(y,"true"),r.remove(),d=null,e(new Error("Failed to load Podlove embed script"))},{once:!0});return}}const o=document.createElement("script");o.src=t,o.async=!0,o.setAttribute(b,"true"),o.addEventListener("load",()=>{o.setAttribute(g,"true"),a()},{once:!0}),o.addEventListener("error",()=>{o.setAttribute(y,"true"),o.remove(),d=null,e(new Error("Failed to load Podlove embed script"))},{once:!0}),document.head.appendChild(o)}),d)}function $(t){return typeof window.requestIdleCallback=="function"?window.requestIdleCallback(()=>t(),{timeout:C}):window.setTimeout(()=>t(),0)}function z(t){if(typeof window.cancelIdleCallback=="function"){window.cancelIdleCallback(t);return}window.clearTimeout(t)}function q(){var a,e;const t=document.documentElement.getAttribute("data-bs-theme")||document.documentElement.getAttribute("data-theme")||((a=document.body)==null?void 0:a.getAttribute("data-bs-theme"))||((e=document.body)==null?void 0:e.getAttribute("data-theme"));return t==="light"||t==="dark"?t:null}function G(){const t=q();return t?t==="dark":typeof window.matchMedia!="function"?!1:window.matchMedia("(prefers-color-scheme: dark)").matches}function N(t){if(!G())return t;const a=t.indexOf("#"),e=a===-1?t:t.slice(0,a),r=a===-1?"":t.slice(a),o=e.indexOf("?"),l=o===-1?e:e.slice(0,o),c=o===-1?"":e.slice(o+1),s=new URLSearchParams(c);if(s.has(L))return t;s.set(L,"dark");const n=s.toString();return n?`${l}?${n}${r}`:`${l}${r}`}class k extends HTMLElement{constructor(){super();i(this,"observer");i(this,"isInitialized");i(this,"isScheduled");i(this,"idleHandle");i(this,"loadButton");i(this,"clickHandler");i(this,"errorMessage");i(this,"playerDiv");this.observer=null,this.isInitialized=!1,this.isScheduled=!1,this.idleHandle=null,this.loadButton=null,this.clickHandler=null,this.errorMessage=null,this.playerDiv=null}connectedCallback(){const e=this.shouldClickToLoad();if(this.renderPlaceholder(e),e){this.setupClickToLoad();return}if(document.readyState==="complete"){this.observeElement();return}M().then(()=>this.observeElement())}disconnectedCallback(){this.observer&&this.observer.unobserve(this),this.loadButton&&this.clickHandler&&this.loadButton.removeEventListener("click",this.clickHandler),this.idleHandle!==null&&(z(this.idleHandle),this.idleHandle=null)}shouldClickToLoad(){return this.getAttribute(w)===x}renderPlaceholder(e){if(this.querySelector(".podlove-player-container"))return;if(!document.getElementById(E)){const l=document.createElement("style");l.id=E,l.textContent=`
        podlove-player .podlove-player-container {
          width: 100%;
          max-width: 936px;
          min-height: 300px;
          margin: 0 auto;
          background-color: ${u};
        }
        @media (max-width: 768px) {
          podlove-player .podlove-player-container {
            max-width: 366px;
            min-height: 500px;
          }
        }
        podlove-player .podlove-player-click-to-load {
          display: flex;
          flex-direction: column;
          gap: 0.8rem;
          align-items: center;
          justify-content: center;
          background: #f6f6f6;
          border: 1px solid #e3e3e3;
          border-radius: 8px;
        }
        podlove-player .podlove-player-button {
          appearance: none;
          border: 1px solid #1a1a1a;
          background: #1a1a1a;
          color: #ffffff;
          border-radius: 999px;
          font-size: 0.95rem;
          padding: 0.6rem 1.4rem;
          cursor: pointer;
        }
        podlove-player .podlove-player-button:focus-visible {
          outline: 3px solid #6aa5ff;
          outline-offset: 3px;
        }
        podlove-player .podlove-player-button:disabled {
          opacity: 0.7;
          cursor: progress;
        }
        podlove-player .podlove-player-error {
          margin: 1.2rem;
          color: #b42318;
          font-size: 0.95rem;
          text-align: center;
        }
        podlove-player .podlove-player-container iframe {
          width: 100%;
          height: 100%;
          border: none;
          background-color: ${u};
        }
        @media (prefers-color-scheme: dark) {
          podlove-player .podlove-player-container {
            background-color: ${p};
          }
          podlove-player .podlove-player-container iframe {
            background-color: ${p};
            color-scheme: dark;
          }
        }
        html[data-bs-theme="dark"] podlove-player .podlove-player-container,
        html[data-theme="dark"] podlove-player .podlove-player-container,
        body[data-bs-theme="dark"] podlove-player .podlove-player-container,
        body[data-theme="dark"] podlove-player .podlove-player-container {
          background-color: ${p};
        }
        html[data-bs-theme="dark"] podlove-player .podlove-player-container iframe,
        html[data-theme="dark"] podlove-player .podlove-player-container iframe,
        body[data-bs-theme="dark"] podlove-player .podlove-player-container iframe,
        body[data-theme="dark"] podlove-player .podlove-player-container iframe {
          background-color: ${p};
          color-scheme: dark;
        }
        html[data-bs-theme="light"] podlove-player .podlove-player-container iframe,
        html[data-theme="light"] podlove-player .podlove-player-container iframe,
        body[data-bs-theme="light"] podlove-player .podlove-player-container iframe,
        body[data-theme="light"] podlove-player .podlove-player-container iframe {
          background-color: ${u};
          color-scheme: light;
        }
        html[data-bs-theme="light"] podlove-player .podlove-player-container,
        html[data-theme="light"] podlove-player .podlove-player-container,
        body[data-bs-theme="light"] podlove-player .podlove-player-container,
        body[data-theme="light"] podlove-player .podlove-player-container {
          background-color: ${u};
        }
      `,document.head.appendChild(l)}const r=document.createElement("div");r.classList.add("podlove-player-container"),e&&r.classList.add("podlove-player-click-to-load"),this.appendChild(r);const o=document.createElement("p");if(o.classList.add("podlove-player-error"),o.hidden=!0,o.setAttribute("role","alert"),o.textContent=S,r.appendChild(o),this.errorMessage=o,e){const l=document.createElement("button");l.type="button",l.textContent=P,l.classList.add("podlove-player-button"),l.setAttribute("aria-label","Load audio player"),r.appendChild(l),this.loadButton=l}}observeElement(){this.observer=R(),this.observer.observe(this)}setupClickToLoad(){this.loadButton&&(this.clickHandler=()=>{this.clearError(),this.loadButton&&(this.loadButton.disabled=!0,this.loadButton.textContent=O),this.scheduleInitialize()},this.loadButton.addEventListener("click",this.clickHandler))}scheduleInitialize(){this.isInitialized||this.isScheduled||(this.isScheduled=!0,this.idleHandle=$(()=>{this.idleHandle=null,this.isScheduled=!1,this.initializePlayer()}))}initializePlayer(){if(this.isInitialized)return;const e=this.querySelector(".podlove-player-container");if(!e)return;const r=this.getAttribute("data-url");if(!r)return;let o=this.getAttribute("id");o||(o=`podlove-player-${Date.now()}`,this.setAttribute("id",o)),this.dataset.playerInstanceId||(f+=1,this.dataset.playerInstanceId=String(f));const l=`${o}-player-${this.dataset.playerInstanceId}`;this.isInitialized=!0,this.clearError();const c=N(this.getAttribute("data-config")||"/api/audios/player_config/"),s=this.getAttribute("data-template");let n=this.getAttribute("data-embed")||"https://cdn.podlove.org/web-player/5.x/embed.js";const{hostname:A,port:T}=window.location,v=this.getOrCreatePlayerDiv(e,l,s);if(typeof podlovePlayer=="function"){podlovePlayer(v,r,c),this.finalizeLoad(e);return}A==="localhost"&&n.startsWith("/")&&(n=`http://localhost:${T}${n}`),H(n).then(()=>{if(typeof podlovePlayer=="function"){podlovePlayer(v,r,c),this.finalizeLoad(e);return}this.handleLoadError()}).catch(()=>{this.handleLoadError()})}getOrCreatePlayerDiv(e,r,o){return this.playerDiv||(this.playerDiv=document.createElement("div"),this.playerDiv.classList.add("podlove-player-host")),e.contains(this.playerDiv)||e.appendChild(this.playerDiv),this.playerDiv.id=r,o!==null?this.playerDiv.setAttribute("data-template",o):this.playerDiv.removeAttribute("data-template"),this.playerDiv}finalizeLoad(e){e instanceof HTMLElement&&(e.style.minHeight="auto"),this.style.minHeight="auto",this.loadButton&&(this.loadButton.remove(),this.loadButton=null),e.classList.remove("podlove-player-click-to-load"),this.clearError()}clearError(){this.errorMessage&&(this.errorMessage.hidden=!0)}handleLoadError(){this.isInitialized=!1,this.errorMessage&&(this.errorMessage.hidden=!1),this.loadButton&&(this.loadButton.disabled=!1,this.loadButton.textContent=B)}}customElements.define("podlove-player",k);
