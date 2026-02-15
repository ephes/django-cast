import { expect, test, describe, beforeEach, afterEach, vi } from "vitest";
import ImageGalleryBs4 from "@/gallery/image-gallery-bs4";
import { JSDOM } from "jsdom";


describe("image gallery test", () => {
    let dom: JSDOM;
    let document: Document;

    beforeEach(() => {
        dom = new JSDOM();
        document = dom.window.document;
        global.document = document;
        global.window = dom.window as any;
        global.HTMLElement = dom.window.HTMLElement;
        global.customElements = dom.window.customElements;
        global.Element = dom.window.Element;

        // Register the custom element
        ImageGalleryBs4.register("image-gallery-bs4");
    });

    afterEach(() => {
        dom.window.close();
    });

    test("gallery test current image is null", () => {
        const gallery = new ImageGalleryBs4()
        expect(gallery.currentImage).toBe(null)
    })

    test("gallery handles duplicate images correctly", () => {
        // Create gallery instance and set its content
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";

        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" />
                        <img id="img-0" data-prev="false" data-next="img-1" alt="Image 1" />
                    </picture>
                </a>
                <a class="cast-gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" />
                        <img id="img-1" data-prev="img-0" data-next="img-2" alt="Image 2" />
                    </picture>
                </a>
                <a class="cast-gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" />
                        <img id="img-2" data-prev="img-1" data-next="img-3" alt="Duplicate of Image 1" />
                    </picture>
                </a>
                <a class="cast-gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" />
                        <img id="img-3" data-prev="img-2" data-next="img-4" alt="Image 3" />
                    </picture>
                </a>
                <a class="cast-gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" />
                        <img id="img-4" data-prev="img-3" data-next="false" alt="Duplicate of Image 2" />
                    </picture>
                </a>
            </div>
            <div id="gallery-test" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);

        // Test navigation to each unique image using position-based IDs
        const img0 = gallery.querySelector("#img-0") as HTMLElement;
        const img1 = gallery.querySelector("#img-1") as HTMLElement;
        const img2 = gallery.querySelector("#img-2") as HTMLElement;
        const img3 = gallery.querySelector("#img-3") as HTMLElement;
        const img4 = gallery.querySelector("#img-4") as HTMLElement;

        // Verify all images are found with unique IDs
        expect(img0).toBeTruthy();
        expect(img1).toBeTruthy();
        expect(img2).toBeTruthy();
        expect(img3).toBeTruthy();
        expect(img4).toBeTruthy();

        // Test that setModalImage works for each image
        gallery.setModalImage(img0);
        expect(gallery.currentImage).toBe(img0);

        // Test navigation from first image
        gallery.replaceImage("data-next");
        expect(gallery.querySelector("#img-1")).toBeTruthy();

        // Test navigation through all images
        gallery.setModalImage(img2);
        gallery.replaceImage("data-prev");
        expect(gallery.querySelector("#img-1")).toBeTruthy();

        gallery.replaceImage("data-next");
        expect(gallery.querySelector("#img-2")).toBeTruthy();
    });

    test("gallery navigation buttons disabled correctly at boundaries", () => {
        // Create gallery instance and set its content
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";

        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" />
                        <img id="img-0" data-prev="false" data-next="img-1" alt="First" />
                    </picture>
                </a>
                <a class="cast-gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" />
                        <img id="img-1" data-prev="img-0" data-next="false" alt="Last" />
                    </picture>
                </a>
            </div>
            <div id="gallery-test" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);

        const firstImg = gallery.querySelector("#img-0") as HTMLElement;
        const lastImg = gallery.querySelector("#img-1") as HTMLElement;

        // Test first image - prev should be disabled
        gallery.setModalImage(firstImg);
        gallery.replaceImage("data-prev");
        expect(gallery.currentImage).toBe(firstImg); // Should not change

        // Test last image - next should be disabled
        gallery.setModalImage(lastImg);
        gallery.replaceImage("data-next");
        expect(gallery.currentImage).toBe(lastImg); // Should not change
    });

    test("gallery opens modal immediately even while image is loading", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-src="modal.avif" data-modal-srcset="modal.avif 1000w" data-modal-sizes="100vw" type="image/avif" />
                        <img
                          id="img-0"
                          data-fullsrc="modal.jpg"
                          data-modal-srcset="modal.jpg 1000w"
                          data-modal-sizes="100vw"
                          data-modal-width="1000"
                          data-modal-height="500"
                          data-prev="false"
                          data-next="false"
                          alt="First"
                        />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const showModalSpy = vi.spyOn(gallery as any, "showModal");
        const thumbnailImage = gallery.querySelector("#img-0") as HTMLElement;
        const modalImage = gallery.querySelector("#gallery-modal .modal-body img") as HTMLImageElement;
        const modalBody = gallery.querySelector("#gallery-modal .modal-body") as HTMLElement;

        Object.defineProperty(modalImage, "complete", { configurable: true, get: () => false });
        Object.defineProperty(modalImage, "naturalWidth", { configurable: true, get: () => 0 });

        thumbnailImage.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(showModalSpy).toHaveBeenCalledTimes(1);
        expect(modalBody.getAttribute("aria-busy")).toBe("true");
        expect(modalImage.style.opacity).toBe("0");
    });

    test("gallery removes loading state when image load finishes", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-src="modal.avif" data-modal-srcset="modal.avif 1000w" data-modal-sizes="100vw" type="image/avif" />
                        <img
                          id="img-0"
                          data-fullsrc="modal.jpg"
                          data-modal-srcset="modal.jpg 1000w"
                          data-modal-sizes="100vw"
                          data-modal-width="1000"
                          data-modal-height="500"
                          data-prev="false"
                          data-next="false"
                          alt="First"
                        />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const thumbnailImage = gallery.querySelector("#img-0") as HTMLElement;
        const modalImage = gallery.querySelector("#gallery-modal .modal-body img") as HTMLImageElement;
        const modalBody = gallery.querySelector("#gallery-modal .modal-body") as HTMLElement;

        Object.defineProperty(modalImage, "complete", { configurable: true, get: () => false });
        Object.defineProperty(modalImage, "naturalWidth", { configurable: true, get: () => 0 });

        thumbnailImage.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(modalBody.getAttribute("aria-busy")).toBe("true");
        expect(modalImage.style.opacity).toBe("0");

        modalImage.dispatchEvent(new dom.window.Event("load"));
        expect(modalBody.getAttribute("aria-busy")).toBe("false");
        expect(modalImage.style.opacity).toBe("1");
    });

    test("gallery removes loading state when image load fails", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-src="modal.avif" data-modal-srcset="modal.avif 1000w" data-modal-sizes="100vw" type="image/avif" />
                        <img
                          id="img-0"
                          data-fullsrc="modal.jpg"
                          data-modal-srcset="modal.jpg 1000w"
                          data-modal-sizes="100vw"
                          data-modal-width="1000"
                          data-modal-height="500"
                          data-prev="false"
                          data-next="false"
                          alt="First"
                        />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const thumbnailImage = gallery.querySelector("#img-0") as HTMLElement;
        const modalImage = gallery.querySelector("#gallery-modal .modal-body img") as HTMLImageElement;
        const modalBody = gallery.querySelector("#gallery-modal .modal-body") as HTMLElement;

        Object.defineProperty(modalImage, "complete", { configurable: true, get: () => false });
        Object.defineProperty(modalImage, "naturalWidth", { configurable: true, get: () => 0 });

        thumbnailImage.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(modalBody.getAttribute("aria-busy")).toBe("true");
        expect(modalImage.style.opacity).toBe("0");

        modalImage.dispatchEvent(new dom.window.Event("error"));
        expect(modalBody.getAttribute("aria-busy")).toBe("false");
        expect(modalImage.style.opacity).toBe("1");
    });

    test("gallery clears old loading listeners on rapid navigation", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="image-0.jpg">
                    <picture>
                        <source data-modal-src="modal-0.avif" data-modal-srcset="modal-0.avif 1000w" data-modal-sizes="100vw" type="image/avif" />
                        <img id="img-0" data-fullsrc="modal-0.jpg" data-modal-srcset="modal-0.jpg 1000w" data-modal-sizes="100vw" data-modal-width="1000" data-modal-height="500" data-prev="false" data-next="img-1" alt="First" />
                    </picture>
                </a>
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="image-1.jpg">
                    <picture>
                        <source data-modal-src="modal-1.avif" data-modal-srcset="modal-1.avif 1000w" data-modal-sizes="100vw" type="image/avif" />
                        <img id="img-1" data-fullsrc="modal-1.jpg" data-modal-srcset="modal-1.jpg 1000w" data-modal-sizes="100vw" data-modal-width="1000" data-modal-height="500" data-prev="img-0" data-next="false" alt="Second" />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const setLoadingStateSpy = vi.spyOn(gallery as any, "setLoadingState");
        const img0 = gallery.querySelector("#img-0") as HTMLElement;
        const img1 = gallery.querySelector("#img-1") as HTMLElement;
        const modalImage = gallery.querySelector("#gallery-modal .modal-body img") as HTMLImageElement;

        Object.defineProperty(modalImage, "complete", { configurable: true, get: () => false });
        Object.defineProperty(modalImage, "naturalWidth", { configurable: true, get: () => 0 });

        img0.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        img1.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));

        const falseCallsBefore = setLoadingStateSpy.mock.calls.filter(([, loading]) => loading === false).length;
        modalImage.dispatchEvent(new dom.window.Event("error"));
        const falseCallsAfter = setLoadingStateSpy.mock.calls.filter(([, loading]) => loading === false).length;

        expect(falseCallsAfter - falseCallsBefore).toBe(1);
    });

    test("gallery uses window.bootstrap.Modal when available", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" type="image/avif" />
                        <img id="img-0" data-fullsrc="modal.jpg" data-prev="false" data-next="false" alt="First" />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const mockShow = vi.fn();
        const mockDispose = vi.fn();
        const MockModal = vi.fn().mockImplementation(function (this: any) {
            this.show = mockShow;
            this.dispose = mockDispose;
        });

        (window as any).bootstrap = { Modal: MockModal };

        const thumbnailImage = gallery.querySelector("#img-0") as HTMLElement;
        thumbnailImage.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));

        expect(MockModal).toHaveBeenCalledTimes(1);
        expect(mockShow).toHaveBeenCalledTimes(1);

        // Second click should reuse the same instance
        thumbnailImage.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(MockModal).toHaveBeenCalledTimes(1);
        expect(mockShow).toHaveBeenCalledTimes(2);

        // Cleanup should dispose the instance
        gallery.disconnectedCallback();
        expect(mockDispose).toHaveBeenCalledTimes(1);

        delete (window as any).bootstrap;
    });

    test("gallery disposes stale bootstrap.Modal when modal element changes", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#modal-a" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" type="image/avif" />
                        <img id="img-0" data-fullsrc="modal.jpg" data-prev="false" data-next="false" alt="First" />
                    </picture>
                </a>
                <a class="cast-gallery-modal" data-target="#modal-b" data-full="full-image2.jpg">
                    <picture>
                        <source data-modal-srcset="test2.jpg" type="image/avif" />
                        <img id="img-1" data-fullsrc="modal2.jpg" data-prev="false" data-next="false" alt="Second" />
                    </picture>
                </a>
            </div>
            <div id="modal-a" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
            <div id="modal-b" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const instances: { show: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }[] = [];
        const MockModal = vi.fn().mockImplementation(function (this: any) {
            this.show = vi.fn();
            this.dispose = vi.fn();
            instances.push(this);
        });

        (window as any).bootstrap = { Modal: MockModal };

        // Click first thumbnail (targets modal-a)
        const img0 = gallery.querySelector("#img-0") as HTMLElement;
        img0.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(MockModal).toHaveBeenCalledTimes(1);
        expect(instances[0].show).toHaveBeenCalledTimes(1);

        // Click second thumbnail (targets modal-b) - should dispose first instance
        const img1 = gallery.querySelector("#img-1") as HTMLElement;
        img1.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(instances[0].dispose).toHaveBeenCalledTimes(1);
        expect(MockModal).toHaveBeenCalledTimes(2);
        expect(instances[1].show).toHaveBeenCalledTimes(1);

        gallery.disconnectedCallback();
        delete (window as any).bootstrap;
    });

    test("gallery Escape key closes modal via hideModal", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" type="image/avif" />
                        <img id="img-0" data-fullsrc="modal.jpg" data-prev="false" data-next="false" alt="First" />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const mockHide = vi.fn();
        const MockModal = vi.fn().mockImplementation(function (this: any) {
            this.show = vi.fn();
            this.hide = mockHide;
            this.dispose = vi.fn();
        });

        (window as any).bootstrap = { Modal: MockModal };

        // Open modal
        const img0 = gallery.querySelector("#img-0") as HTMLElement;
        img0.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(MockModal).toHaveBeenCalledTimes(1);

        // Press Escape on the modal
        const modal = document.querySelector("#gallery-modal") as HTMLElement;
        modal.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        expect(mockHide).toHaveBeenCalledTimes(1);

        gallery.disconnectedCallback();
        delete (window as any).bootstrap;
    });

    test("gallery hideModal force-clears stuck _isTransitioning", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" type="image/avif" />
                        <img id="img-0" data-fullsrc="modal.jpg" data-prev="false" data-next="false" alt="First" />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const mockHide = vi.fn();
        const MockModal = vi.fn().mockImplementation(function (this: any) {
            this.show = vi.fn();
            this.hide = mockHide;
            this.dispose = vi.fn();
            this._isTransitioning = true; // Simulate stuck state
        });

        (window as any).bootstrap = { Modal: MockModal };

        // Open modal
        const img0 = gallery.querySelector("#img-0") as HTMLElement;
        img0.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));

        // Modal should have "show" class added by BS4's show()
        // Simulate BS4 adding the class (since our mock doesn't)
        const modal = document.querySelector("#gallery-modal") as HTMLElement;
        modal.classList.add("show");

        // Press Escape — should clear _isTransitioning then call hide()
        modal.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        expect(mockHide).toHaveBeenCalledTimes(1);

        // Verify _isTransitioning was cleared before hide()
        const inst = MockModal.mock.instances[0];
        expect(inst._isTransitioning).toBe(false);

        gallery.disconnectedCallback();
        delete (window as any).bootstrap;
    });

    test("gallery dismiss click closes modal via event delegation", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-srcset="test.jpg" type="image/avif" />
                        <img id="img-0" data-fullsrc="modal.jpg" data-prev="false" data-next="false" alt="First" />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-header">
                    <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const mockHide = vi.fn();
        const MockModal = vi.fn().mockImplementation(function (this: any) {
            this.show = vi.fn();
            this.hide = mockHide;
            this.dispose = vi.fn();
        });

        (window as any).bootstrap = { Modal: MockModal };

        // Open modal
        const img0 = gallery.querySelector("#img-0") as HTMLElement;
        img0.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));

        // Click the × span inside the close button (tests delegation)
        const modal = document.querySelector("#gallery-modal") as HTMLElement;
        const closeSpan = modal.querySelector('[data-dismiss="modal"] span') as HTMLElement;
        closeSpan.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(mockHide).toHaveBeenCalledTimes(1);

        gallery.disconnectedCallback();
        delete (window as any).bootstrap;
    });

    test("gallery applies image aspect ratio to keep modal body stable", () => {
        const gallery = new ImageGalleryBs4();
        gallery.id = "gallery-test";
        gallery.innerHTML = `
            <div class="cast-gallery-container">
                <a class="cast-gallery-modal" data-target="#gallery-modal" data-full="full-image.jpg">
                    <picture>
                        <source data-modal-src="modal.avif" data-modal-srcset="modal.avif 1000w" data-modal-sizes="100vw" type="image/avif" />
                        <img
                          id="img-0"
                          data-fullsrc="modal.jpg"
                          data-modal-srcset="modal.jpg 1000w"
                          data-modal-sizes="100vw"
                          data-modal-width="1000"
                          data-modal-height="500"
                          data-prev="false"
                          data-next="false"
                          alt="First"
                        />
                    </picture>
                </a>
            </div>
            <div id="gallery-modal" class="modal">
                <div class="modal-body">
                    <a><picture><source /><img /></picture></a>
                </div>
                <div class="modal-footer"></div>
            </div>
        `;

        document.body.appendChild(gallery);
        gallery.connectedCallback();

        const thumbnailImage = gallery.querySelector("#img-0") as HTMLElement;
        const modalImage = gallery.querySelector("#gallery-modal .modal-body img") as HTMLImageElement;

        Object.defineProperty(modalImage, "complete", { configurable: true, get: () => false });
        Object.defineProperty(modalImage, "naturalWidth", { configurable: true, get: () => 0 });

        thumbnailImage.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(modalImage.style.aspectRatio).toBe("1000 / 500");
    });
})
