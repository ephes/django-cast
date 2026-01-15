export default class ImageGalleryBs4 extends HTMLElement {
    currentImage: HTMLElement | null;
    currentModal: HTMLElement | null;
    private boundThumbnailClick: (event: Event) => void;
    private boundFooterClick: (event: Event) => void;
    private boundKeydown: (event: KeyboardEvent) => void;
	constructor () {
		super();
        this.currentImage = null;
        this.currentModal = null;
        this.boundThumbnailClick = this.handleThumbnailClick.bind(this);
        this.boundFooterClick = this.handleFooterClick.bind(this);
        this.boundKeydown = this.handleKeydown.bind(this);
	}
    static register(tagName: string):void {
        console.log("Registering image-gallery-bs4!");
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
        console.log("modalBody: ", modalBody)
        // console.log("modalBody parent.parent.parent: ", modalBody.parentNode.parentNode.parentNode);
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
        event.preventDefault();
        const target = event.target as HTMLElement;
        // Find the img element within the clicked link
        const link = event.currentTarget as HTMLElement;
        const img = link.querySelector('img');
        if (img) {
            const modal = this.resolveModal(link);
            this.setModalImage(img, modal);
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
        // Add event listeners to thumbnail links - click -> open modal image
        let thumbnailLinks = this.querySelectorAll(".cast-gallery-container > a");
        thumbnailLinks.forEach((link) => {
            if (!link.classList.contains("event-added")) {
                link.addEventListener("click", this.boundThumbnailClick);
                link.classList.add("event-added");
            }
        });
    }

    disconnectedCallback() {
        // Remove event listeners from thumbnail links
        let thumbnailLinks = this.querySelectorAll(".cast-gallery-container > a");
        thumbnailLinks.forEach((link) => {
            link.removeEventListener("click", this.boundThumbnailClick);
            link.classList.remove("event-added");
        });
        this.cleanupModal();
    }
}

// Define the new web component
ImageGalleryBs4.register("image-gallery-bs4");
