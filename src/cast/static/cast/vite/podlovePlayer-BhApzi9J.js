class d extends HTMLElement{constructor(){super(),this.observer=null,this.shadow=this.attachShadow({mode:"open"})}connectedCallback(){this.renderPlaceholder(),document.readyState==="complete"?this.observeElement():window.addEventListener("load",()=>{this.observeElement()},{once:!0})}disconnectedCallback(){this.observer&&this.observer.disconnect()}renderPlaceholder(){const e=document.createElement("div");e.classList.add("podlove-player-container");const t=document.createElement("style");t.textContent=`
      .podlove-player-container {
        width: 100%;
        max-width: 936px;
        min-height: 300px;
        margin: 0 auto;
      }
      @media (max-width: 768px) {
        .podlove-player-container {
          max-width: 366px;
          min-height: 500px;
        }
      }
      .podlove-player-container iframe {
        width: 100%;
        height: 100%;
        border: none;
      }
    `,this.shadow.appendChild(t),this.shadow.appendChild(e)}observeElement(){this.observer=new IntersectionObserver((e,t)=>{e.forEach(i=>{i.isIntersecting&&(this.initializePlayer(),t.unobserve(this))})}),this.observer.observe(this)}initializePlayer(){const e=this.shadow.querySelector(".podlove-player-container"),t=this.getAttribute("id")||`podlove-player-${Date.now()}`,i=this.getAttribute("data-url"),l=this.getAttribute("data-config")||"/api/audios/player_config/",a=this.getAttribute("data-template");let n=this.getAttribute("data-embed")||"https://cdn.podlove.org/web-player/5.x/embed.js";const{hostname:r,port:s}=window.location;console.log("data template: ",a);const o=document.createElement("div");o.id=t,a!==null&&o.setAttribute("data-template",a),e.appendChild(o),typeof podlovePlayer=="function"?podlovePlayer(o,i,l):(r==="localhost"&&n.startsWith("/")&&(n=`http://localhost:${s}${n}`),import(n).then(()=>{podlovePlayer(o,i,l)}))}}console.log("Registering podlove-player!");customElements.define("podlove-player",d);
