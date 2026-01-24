var g=Object.defineProperty;var L=(r,o,e)=>o in r?g(r,o,{enumerable:!0,configurable:!0,writable:!0,value:e}):r[o]=e;var a=(r,o,e)=>L(r,typeof o!="symbol"?o+"":o,e);let n=null,s=null,c=null;const T=200,A="200px 0px",C="data-load-mode",_="click",I="Load player",w="Loading player...",D="Try again",P="Unable to load the audio player. Please try again.",h="data-podlove-embed",f="data-podlove-embed-loaded",u="data-podlove-embed-failed",v="podlove-player-styles";function x(){return document.readyState==="complete"?Promise.resolve():(s||(s=new Promise(r=>{window.addEventListener("load",()=>r(),{once:!0})})),s)}function B(){return c||(c=new IntersectionObserver((r,o)=>{r.forEach(e=>{if(!e.isIntersecting)return;const t=e.target;t instanceof y&&t.scheduleInitialize(),o.unobserve(t)})},{rootMargin:A})),c}function k(r){return typeof podlovePlayer=="function"?Promise.resolve():n||(n=new Promise((o,e)=>{const t=document.querySelector(`script[${h}]`);if(t){if(t.getAttribute(f)==="true"&&typeof podlovePlayer=="function"){o();return}if(t.getAttribute(u)==="true")t.remove();else{t.addEventListener("load",()=>o(),{once:!0}),t.addEventListener("error",()=>{t.setAttribute(u,"true"),t.remove(),n=null,e(new Error("Failed to load Podlove embed script"))},{once:!0});return}}const i=document.createElement("script");i.src=r,i.async=!0,i.setAttribute(h,"true"),i.addEventListener("load",()=>{i.setAttribute(f,"true"),o()},{once:!0}),i.addEventListener("error",()=>{i.setAttribute(u,"true"),i.remove(),n=null,e(new Error("Failed to load Podlove embed script"))},{once:!0}),document.head.appendChild(i)}),n)}function O(r){return typeof window.requestIdleCallback=="function"?window.requestIdleCallback(()=>r(),{timeout:T}):window.setTimeout(()=>r(),0)}function S(r){if(typeof window.cancelIdleCallback=="function"){window.cancelIdleCallback(r);return}window.clearTimeout(r)}class y extends HTMLElement{constructor(){super();a(this,"observer");a(this,"isInitialized");a(this,"isScheduled");a(this,"idleHandle");a(this,"loadButton");a(this,"clickHandler");a(this,"errorMessage");a(this,"playerDiv");this.observer=null,this.isInitialized=!1,this.isScheduled=!1,this.idleHandle=null,this.loadButton=null,this.clickHandler=null,this.errorMessage=null,this.playerDiv=null}connectedCallback(){const e=this.shouldClickToLoad();if(this.renderPlaceholder(e),e){this.setupClickToLoad();return}if(document.readyState==="complete"){this.observeElement();return}x().then(()=>this.observeElement())}disconnectedCallback(){this.observer&&this.observer.unobserve(this),this.loadButton&&this.clickHandler&&this.loadButton.removeEventListener("click",this.clickHandler),this.idleHandle!==null&&(S(this.idleHandle),this.idleHandle=null)}shouldClickToLoad(){return this.getAttribute(C)===_}renderPlaceholder(e){if(this.querySelector(".podlove-player-container"))return;if(!document.getElementById(v)){const l=document.createElement("style");l.id=v,l.textContent=`
        podlove-player .podlove-player-container {
          width: 100%;
          max-width: 936px;
          min-height: 300px;
          margin: 0 auto;
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
        }
      `,document.head.appendChild(l)}const t=document.createElement("div");t.classList.add("podlove-player-container"),e&&t.classList.add("podlove-player-click-to-load"),this.appendChild(t);const i=document.createElement("p");if(i.classList.add("podlove-player-error"),i.hidden=!0,i.setAttribute("role","alert"),i.textContent=P,t.appendChild(i),this.errorMessage=i,e){const l=document.createElement("button");l.type="button",l.textContent=I,l.classList.add("podlove-player-button"),l.setAttribute("aria-label","Load audio player"),t.appendChild(l),this.loadButton=l}}observeElement(){this.observer=B(),this.observer.observe(this)}setupClickToLoad(){this.loadButton&&(this.clickHandler=()=>{this.clearError(),this.loadButton&&(this.loadButton.disabled=!0,this.loadButton.textContent=w),this.scheduleInitialize()},this.loadButton.addEventListener("click",this.clickHandler))}scheduleInitialize(){this.isInitialized||this.isScheduled||(this.isScheduled=!0,this.idleHandle=O(()=>{this.idleHandle=null,this.isScheduled=!1,this.initializePlayer()}))}initializePlayer(){if(this.isInitialized)return;const e=this.querySelector(".podlove-player-container");if(!e)return;const t=this.getAttribute("data-url");if(!t)return;let i=this.getAttribute("id");i||(i=`podlove-player-${Date.now()}`,this.setAttribute("id",i));const l=`${i}-player`;this.isInitialized=!0,this.clearError();const p=this.getAttribute("data-config")||"/api/audios/player_config/",m=this.getAttribute("data-template");let d=this.getAttribute("data-embed")||"https://cdn.podlove.org/web-player/5.x/embed.js";const{hostname:b,port:E}=window.location;if(this.getOrCreatePlayerDiv(e,l,m),typeof podlovePlayer=="function"){podlovePlayer(`#${l}`,t,p),this.finalizeLoad(e);return}b==="localhost"&&d.startsWith("/")&&(d=`http://localhost:${E}${d}`),k(d).then(()=>{if(typeof podlovePlayer=="function"){podlovePlayer(`#${l}`,t,p),this.finalizeLoad(e);return}this.handleLoadError()}).catch(()=>{this.handleLoadError()})}getOrCreatePlayerDiv(e,t,i){return this.playerDiv||(this.playerDiv=document.createElement("div"),this.playerDiv.classList.add("podlove-player-host")),e.contains(this.playerDiv)||e.appendChild(this.playerDiv),this.playerDiv.id=t,i!==null?this.playerDiv.setAttribute("data-template",i):this.playerDiv.removeAttribute("data-template"),this.playerDiv}finalizeLoad(e){this.loadButton&&(this.loadButton.remove(),this.loadButton=null),e.classList.remove("podlove-player-click-to-load"),this.clearError()}clearError(){this.errorMessage&&(this.errorMessage.hidden=!0)}handleLoadError(){this.isInitialized=!1,this.errorMessage&&(this.errorMessage.hidden=!1),this.loadButton&&(this.loadButton.disabled=!1,this.loadButton.textContent=D)}}customElements.define("podlove-player",y);
