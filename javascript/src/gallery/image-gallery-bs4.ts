export default class ImageGalleryBs4 extends HTMLElement {
    currentImage: HTMLElement | null;
    currentModal: HTMLElement | null;
    private boundThumbnailClick: (event: Event) => void;
    private boundFooterClick: (event: Event) => void;
    private boundKeydown: (event: KeyboardEvent) => void;
    private pendingModalImage: HTMLImageElement | null;
    private pendingFinalize: (() => void) | null;
    private loadingSequence: number;
	constructor () {
		super();
        this.currentImage = null;
        this.currentModal = null;
        this.boundThumbnailClick = this.handleThumbnailClick.bind(this);
        this.boundFooterClick = this.handleFooterClick.bind(this);
        this.boundKeydown = this.handleKeydown.bind(this);
        this.pendingModalImage = null;
        this.pendingFinalize = null;
        this.loadingSequence = 0;
    }
    static register(tagName: string):void {
        if ("customElements" in window) {
            customElements.define(tagName || "image-gallery-bs4", ImageGalleryBs4);
        }
    }
    replaceImage (direction: string):void {
        if (this.currentImage) {
            const which = this.currentImage.getAttribute(direction);
            if (which === "false") {
                return;
            }
            const targetElement:HTMLElement|null = this.querySelector("#" + which)
            if (targetElement) {
                this.setModalImage(targetElement);
            }
        }
    }
    private resolveModal(link?: HTMLElement): HTMLElement | null {
        if (link) {
            const target = link.getAttribute("data-target");
            if (target) {
                const modal = document.querySelector<HTMLElement>(target);
                if (modal) {
                    return modal;
                }
            }
        }

        return this.querySelector<HTMLElement>(".modal");
    }

    private showModal(modal: HTMLElement | null): void {
        if (!modal) {
            return;
        }
        const jQuery = (window as unknown as { jQuery?: any }).jQuery;
        if (jQuery && typeof jQuery(modal).modal === "function") {
            jQuery(modal).modal("show");
            return;
        }
        modal.classList.add("show");
        modal.style.display = "block";
        modal.removeAttribute("aria-hidden");
        modal.setAttribute("aria-modal", "true");
        document.body.classList.add("modal-open");
    }

    private getModalBody(modal: HTMLElement | null): HTMLElement | null {
        if (!modal) {
            return null;
        }
        return modal.querySelector<HTMLElement>(".modal-body");
    }

    private getModalImage(modal: HTMLElement | null): HTMLImageElement | null {
        if (!modal) {
            return null;
        }
        return modal.querySelector<HTMLImageElement>(".modal-body img");
    }

    private isModalImageReady(modalImage: HTMLImageElement): boolean {
        return modalImage.complete && modalImage.naturalWidth > 0;
    }

    private ensureLoadingIndicator(modalBody: HTMLElement): HTMLElement {
        let indicator = modalBody.querySelector<HTMLElement>(".cast-gallery-loading-indicator");
        if (!indicator) {
            indicator = document.createElement("div");
            indicator.className = "cast-gallery-loading-indicator";
            indicator.style.position = "absolute";
            indicator.style.inset = "0";
            indicator.style.display = "none";
            indicator.style.alignItems = "center";
            indicator.style.justifyContent = "center";
            indicator.style.zIndex = "1";
            indicator.style.pointerEvents = "none";

            const spinner = document.createElement("div");
            spinner.className = "spinner-border text-secondary";
            spinner.setAttribute("role", "status");
            spinner.setAttribute("aria-label", "Loading image");
            indicator.appendChild(spinner);

            modalBody.appendChild(indicator);
        }
        return indicator;
    }

    private setLoadingState(modal: HTMLElement, loading: boolean): void {
        const modalBody = this.getModalBody(modal);
        if (!modalBody) {
            return;
        }
        modalBody.style.position = "relative";
        const indicator = this.ensureLoadingIndicator(modalBody);
        indicator.style.display = loading ? "flex" : "none";
        modalBody.setAttribute("aria-busy", loading ? "true" : "false");

        const modalImage = this.getModalImage(modal);
        if (!modalImage) {
            return;
        }
        modalImage.style.transition = "opacity 120ms ease";
        modalImage.style.opacity = loading ? "0" : "1";
    }

    private applyAspectRatioFromThumbnail(img: HTMLElement, modalImage: HTMLImageElement): void {
        const width = Number(img.getAttribute("data-modal-width") ?? "");
        const height = Number(img.getAttribute("data-modal-height") ?? "");
        if (width > 0 && height > 0) {
            modalImage.style.aspectRatio = `${width} / ${height}`;
            return;
        }
        modalImage.style.removeProperty("aspect-ratio");
    }

    private ensureModalMediaSizing(modalImage: HTMLImageElement): void {
        const modalPicture = modalImage.parentElement as HTMLElement | null;
        if (modalPicture) {
            modalPicture.style.display = "block";
            modalPicture.style.width = "100%";
        }
        const modalLink = modalPicture?.parentElement as HTMLElement | null;
        if (modalLink && modalLink.tagName.toLowerCase() === "a") {
            modalLink.style.display = "block";
            modalLink.style.width = "100%";
        }
    }

    private syncImageLoadingState(modal: HTMLElement, modalImage: HTMLImageElement): void {
        this.clearPendingImageListeners();
        this.setLoadingState(modal, true);
        if (this.isModalImageReady(modalImage)) {
            this.setLoadingState(modal, false);
            return;
        }

        const sequence = ++this.loadingSequence;
        const finalize = () => {
            if (this.currentModal === modal && this.loadingSequence === sequence) {
                this.setLoadingState(modal, false);
            }
            if (this.pendingFinalize === finalize) {
                this.clearPendingImageListeners();
            }
        };
        this.pendingModalImage = modalImage;
        this.pendingFinalize = finalize;
        modalImage.addEventListener("load", finalize, { once: true });
        modalImage.addEventListener("error", finalize, { once: true });
    }

    private clearPendingImageListeners(): void {
        if (this.pendingModalImage && this.pendingFinalize) {
            this.pendingModalImage.removeEventListener("load", this.pendingFinalize);
            this.pendingModalImage.removeEventListener("error", this.pendingFinalize);
        }
        this.pendingModalImage = null;
        this.pendingFinalize = null;
    }

    private showModalImmediately(modal: HTMLElement | null): void {
        if (!modal) {
            return;
        }
        this.showModal(modal);
    }

    private bindModalEvents(modal: HTMLElement): void {
        const modalFooter = modal.querySelector(".modal-footer");
        if (modalFooter && !modalFooter.hasAttribute("data-gallery-footer-bound")) {
            modalFooter.addEventListener("click", this.boundFooterClick);
            modalFooter.setAttribute("data-gallery-footer-bound", "true");
        }

        if (!modal.hasAttribute("data-gallery-keydown-bound")) {
            modal.addEventListener("keydown", this.boundKeydown);
            modal.setAttribute("data-gallery-keydown-bound", "true");
        }
    }

    private unbindModalEvents(modal: HTMLElement): void {
        const modalFooter = modal.querySelector(".modal-footer");
        if (modalFooter && modalFooter.hasAttribute("data-gallery-footer-bound")) {
            modalFooter.removeEventListener("click", this.boundFooterClick);
            modalFooter.removeAttribute("data-gallery-footer-bound");
        }

        if (modal.hasAttribute("data-gallery-keydown-bound")) {
            modal.removeEventListener("keydown", this.boundKeydown);
            modal.removeAttribute("data-gallery-keydown-bound");
        }
    }

    private ensureModalInBody(modal: HTMLElement): void {
        // Bootstrap modals need to live at the document body to avoid scroll/clip issues.
        if (modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
        if (this.id && !modal.hasAttribute("data-gallery-owner")) {
            modal.setAttribute("data-gallery-owner", this.id);
        }
        this.bindModalEvents(modal);
    }

    private cleanupModal(): void {
        this.clearPendingImageListeners();
        const ownerId = this.id;
        const selector = ownerId ? `.modal[data-gallery-owner="${ownerId}"]` : null;
        const modal = selector ? document.querySelector<HTMLElement>(selector) : this.currentModal;
        if (modal && modal.parentElement === document.body) {
            this.unbindModalEvents(modal);
            modal.remove();
        }
        this.currentModal = null;
    }

    setModalImage(img: HTMLElement, modal?: HTMLElement | null):void {
        this.currentImage = img;
        if (!img.parentNode) {
            console.error("No parent node for image: ", img);
            return;
        }
        const thumbnailPicture = img.parentNode;
        if (!thumbnailPicture.parentNode) {
            console.error("No parent node for thumbnail picture: ", thumbnailPicture);
            return;
        }
        const fullUrl = (thumbnailPicture.parentNode as Element).getAttribute("data-full") ?? "";
        const thumbnailSource = thumbnailPicture.querySelector("source");
        if (!thumbnailSource) {
            console.error("No thumbnail source for picture: ", thumbnailPicture);
            return;
        }
        const resolvedModal = modal ?? this.currentModal ?? this.resolveModal();
        if (!resolvedModal) {
            console.error("No modal for image gallery: ", this);
            return;
        }
        this.ensureModalInBody(resolvedModal);
        this.currentModal = resolvedModal;
        const modalBody = resolvedModal.querySelector(".modal-body");
        if (!modalBody) {
            console.error("No modal body for modal: ", this);
            return;
        }
        const modalFooter = resolvedModal.querySelector(".modal-footer");
        if (!modalFooter) {
            console.error("No modal footer for modal: ", this);
            return;
        }

        const sourceAttributes = [
            { attr: "data-modal-srcset", prop: "srcset" },
            { attr: "data-modal-src", prop: "src" },
            { attr: "type", prop: "type" },
            { attr: "data-modal-sizes", prop: "sizes" },
        ];

        const modalSource = modalBody.querySelector("source");
        if (!modalSource) {
            console.error("No modal source for modal body: ", modalBody);
            return;
        }
        for (const { attr, prop } of sourceAttributes) {
            const value = thumbnailSource.getAttribute(attr);
            if (value) {
                modalSource.setAttribute(prop, value);
            }
        }

        const imgAttributes = [
            { attr: "alt", prop: "alt" },
            { attr: "data-prev", prop: "data-prev" },
            { attr: "data-next", prop: "data-next" },
            { attr: "data-fullsrc", prop: "src" },
            { attr: "data-modal-srcset", prop: "srcset" },
            { attr: "data-modal-sizes", prop: "sizes" },
            { attr: "data-modal-height", prop: "height"},
            { attr: "data-modal-width", prop: "width"},
        ];

        const modalImage = modalBody.querySelector("img");
        if (!modalImage) {
            console.error("No modal image for modal body: ", modalBody);
            return;
        }
        (modalImage.parentNode?.parentNode as Element).setAttribute("href", fullUrl);
        for (const { attr, prop } of imgAttributes) {
            const value = img.getAttribute(attr);
            if (value) {
                modalImage.setAttribute(prop, value);
            }
        }
        if (!img.hasAttribute("data-modal-width")) {
            modalImage.removeAttribute("width");
        }
        if (!img.hasAttribute("data-modal-height")) {
            modalImage.removeAttribute("height");
        }
        this.ensureModalMediaSizing(modalImage);
        this.applyAspectRatioFromThumbnail(img, modalImage);
        this.syncImageLoadingState(resolvedModal, modalImage);

        let buttons = "";
        // prev button
        const prev = modalImage.getAttribute("data-prev");
        if (prev !== "false") {
            buttons = buttons + '<button id="data-prev" type="button" class="btn btn-primary">Prev</button>'
        } else {
            buttons = buttons + '<button id="data-prev" type="button" class="btn btn-primary disabled">Prev</button>'
        }

        // next button
        const next = modalImage.getAttribute("data-next");
        if (next !== "false") {
            buttons = buttons + '<button id="data-next" type="button" class="btn btn-primary">Next</button>'
        } else {
            buttons = buttons + '<button id="data-next" type="button" class="btn btn-primary disabled">Next</button>'
        }
        modalFooter.innerHTML = buttons;
    }

    private handleThumbnailClick(event: Event) {
        const target = event.target as HTMLElement | null;
        if (!target) {
            return;
        }
        const link = target.closest("a.cast-gallery-modal") as HTMLElement | null;
        if (!link || !this.contains(link)) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const img = link.querySelector('img');
        if (img) {
            const modal = this.resolveModal(link);
            this.setModalImage(img, modal);
            this.showModalImmediately(modal);
        } else {
            console.error("No img element found in clicked thumbnail");
        }
    }

    private handleFooterClick(event: Event) {
        const target = event.target as Element;
        if (target.matches("#data-prev, #data-next")) {
            this.replaceImage(target.id);
        }
    }

    private handleKeydown(event: KeyboardEvent) {
        if (event.key === "ArrowLeft") {
            this.replaceImage("data-prev");
        }
        if (event.key === "ArrowRight") {
            this.replaceImage("data-next");
        }
    }

    connectedCallback() {
        if (!this.hasAttribute("data-gallery-click-bound")) {
            this.addEventListener("click", this.boundThumbnailClick);
            this.setAttribute("data-gallery-click-bound", "true");
        }
    }

    disconnectedCallback() {
        if (this.hasAttribute("data-gallery-click-bound")) {
            this.removeEventListener("click", this.boundThumbnailClick);
            this.removeAttribute("data-gallery-click-bound");
        }
        this.cleanupModal();
    }
}

// Define the new web component
ImageGalleryBs4.register("image-gallery-bs4");
