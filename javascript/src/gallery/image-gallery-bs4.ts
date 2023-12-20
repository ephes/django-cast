export default class ImageGalleryBs4 extends HTMLElement {
	constructor () {
		super();
        this.currentImage = null;
	}
    static register(tagName) {
        console.log("Registering image-gallery-bs4");
        if ("customElements" in window) {
            customElements.define(tagName || "image-gallery-bs4", ImageGalleryBs4);
        }
    }
    replaceImage (direction) {
        if (this.currentImage) {
            const which = this.currentImage.getAttribute(direction);
            if (which === "false") {
                return;
            }
            const targetElement = this.querySelector('#' + which)
            if (targetElement) {
                this.setModalImage(targetElement);
            }
        }
    }
    setModalImage (img) {
        this.currentImage = img;
        const thumbnailPicture = img.parentNode;
        const fullUrl = thumbnailPicture.parentNode.getAttribute("data-full");
        const thumbnailSource = thumbnailPicture.querySelector('source');
        const modalBody = this.querySelector(".modal-body");
        const modalFooter = this.querySelector(".modal-footer");

        const sourceAttributes = [
            { attr: "data-modal-srcset", prop: "srcset" },
            { attr: "data-modal-src", prop: "src" },
            { attr: "type", prop: "type" },
            { attr: "data-modal-sizes", prop: "sizes" },
        ];

        const modalSource = modalBody.querySelector("source");
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
        modalImage.parentNode.parentNode.setAttribute("href", fullUrl);
        for (const { attr, prop } of imgAttributes) {
            const value = img.getAttribute(attr);
            if (value) {
                modalImage.setAttribute(prop, value);
            }
        }

        let buttons = ''
        // prev button
        const prev = modalImage.getAttribute('data-prev');
        if (prev !== "false") {
            buttons = buttons + '<button id="data-prev" type="button" class="btn btn-primary">Prev</button>'
        } else {
            buttons = buttons + '<button id="data-prev" type="button" class="btn btn-primary disabled">Prev</button>'
        }

        // next button
        const next = modalImage.getAttribute('data-next');
        if (next !== "false") {
            buttons = buttons + '<button id="data-next" type="button" class="btn btn-primary">Next</button>'
        } else {
            buttons = buttons + '<button id="data-next" type="button" class="btn btn-primary disabled">Next</button>'
        }
        modalFooter.innerHTML = buttons;
    }
	connectedCallback () {
		// console.log('connected!', this);
        // add event listeners to thumbnail links - click -> open modal image
        let thumbnailLinks = this.querySelectorAll('.cast-gallery-container > a');
        thumbnailLinks.forEach((link) => {
            if (!link.classList.contains('event-added')) {
                link.addEventListener('click', (event) => {
                    event.preventDefault();
                    this.setModalImage(event.target);
                });
                link.classList.add('event-added');
            }
        });

        // add event listeners to modal buttons - click -> replace image
        const modalFooter = this.querySelector(".modal-footer");
        if (modalFooter) {
            modalFooter.addEventListener("click", (event) => {
                if (event.target.matches("#data-prev, #data-next")) {
                    this.replaceImage(event.target.id);
                }
            });
        }

        // add event listeners to modal - keydown -> replace image
        this.addEventListener('keydown', function (e) {
            if (e.keyCode === 37) {
                this.replaceImage('data-prev')
            }
            if (e.keyCode === 39) {
                this.replaceImage('data-next')
            }
        });
	}
}

// Define the new web component
ImageGalleryBs4.register("image-gallery-bs4");
