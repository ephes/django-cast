export default class ImageGalleryBs4 extends HTMLElement {
    currentImage: HTMLElement | null;
	constructor () {
		super();
        this.currentImage = null;
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
    setModalImage(img: HTMLElement):void {
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
        const modalBody = this.querySelector(`#${this.id} .modal-body`);
        if (!modalBody) {
            console.error("No modal body for modal: ", this);
            return;
        }
        console.log("modalBody: ", modalBody)
        // console.log("modalBody parent.parent.parent: ", modalBody.parentNode.parentNode.parentNode);
        const modalFooter = this.querySelector(`#${this.id} .modal-footer`);
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
        this.setModalImage(event.target as HTMLElement);
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
                link.addEventListener("click", this.handleThumbnailClick.bind(this));
                link.classList.add("event-added");
            }
        });

        // Add event listeners to modal buttons - click -> replace image
        const modalFooter = this.querySelector(".modal-footer");
        if (modalFooter) {
            modalFooter.addEventListener("click", this.handleFooterClick.bind(this));
        }

        // Add event listeners to modal - keydown -> replace image
        this.addEventListener("keydown", this.handleKeydown.bind(this));
    }

    disconnectedCallback() {
        // Remove event listeners from thumbnail links
        let thumbnailLinks = this.querySelectorAll(".cast-gallery-container > a");
        thumbnailLinks.forEach((link) => {
            link.removeEventListener("click", this.handleThumbnailClick);
        });

        // Remove event listeners from modal footer buttons
        const modalFooter = this.querySelector(".modal-footer");
        if (modalFooter) {
            modalFooter.removeEventListener("click", this.handleFooterClick);
        }

        // Remove keydown event listener from the component
        this.removeEventListener("keydown", this.handleKeydown);
    }
}

// Define the new web component
ImageGalleryBs4.register("image-gallery-bs4");
