import { expect, test, describe, beforeEach } from "vitest";
import ImageGallery from "@/gallery/image-gallery-bs4";


describe("image gallery test", () => {
    test("gallery test current image is null", () => {
        const gallery = new ImageGallery()
        console.log("gallery: ", gallery)
        expect(gallery.currentImage).toBe(null)
    })

    describe("navigation with duplicate images", () => {
        let gallery: ImageGallery;
        let container: HTMLElement;

        beforeEach(() => {
            // Create a mock gallery DOM structure with duplicate images
            container = document.createElement("div");
            container.innerHTML = `
                <image-gallery-bs4 id="gallery-test">
                    <div class="cast-gallery-container">
                        <a class="cast-gallery-modal" data-full="image1.jpg">
                            <picture>
                                <source data-modal-src="image1_modal.avif" data-modal-srcset="image1_modal.avif" />
                                <img id="img-pos-0" 
                                     data-prev="false" 
                                     data-next="img-pos-1"
                                     data-modal-src="image1_modal.jpg" />
                            </picture>
                        </a>
                        <a class="cast-gallery-modal" data-full="image2.jpg">
                            <picture>
                                <source data-modal-src="image2_modal.avif" data-modal-srcset="image2_modal.avif" />
                                <img id="img-pos-1" 
                                     data-prev="img-pos-0" 
                                     data-next="img-pos-2"
                                     data-modal-src="image2_modal.jpg" />
                            </picture>
                        </a>
                        <a class="cast-gallery-modal" data-full="image1.jpg">
                            <picture>
                                <source data-modal-src="image1_modal.avif" data-modal-srcset="image1_modal.avif" />
                                <img id="img-pos-2" 
                                     data-prev="img-pos-1" 
                                     data-next="false"
                                     data-modal-src="image1_modal.jpg" />
                            </picture>
                        </a>
                    </div>
                    <div class="modal fade" id="galleryModal-test">
                        <div class="modal-body">
                            <picture>
                                <source class="modal-source" />
                                <img class="modal-image" />
                            </picture>
                        </div>
                        <div class="modal-footer"></div>
                    </div>
                </image-gallery-bs4>
            `;
            document.body.appendChild(container);
            
            gallery = container.querySelector("image-gallery-bs4") as ImageGallery;
            gallery.connectedCallback();
        });

        test("should navigate to next image correctly", () => {
            // Click on first image
            const firstImg = gallery.querySelector("#img-pos-0") as HTMLElement;
            gallery.setModalImage(firstImg);
            
            // Verify current image is set
            expect(gallery.currentImage).toBe(firstImg);
            
            // Navigate to next
            gallery.replaceImage("data-next");
            
            // Should now be on second image
            const secondImg = gallery.querySelector("#img-pos-1") as HTMLElement;
            expect(gallery.currentImage).toBe(secondImg);
        });

        test("should navigate to previous image correctly", () => {
            // Start on second image
            const secondImg = gallery.querySelector("#img-pos-1") as HTMLElement;
            gallery.setModalImage(secondImg);
            
            // Navigate to previous
            gallery.replaceImage("data-prev");
            
            // Should now be on first image
            const firstImg = gallery.querySelector("#img-pos-0") as HTMLElement;
            expect(gallery.currentImage).toBe(firstImg);
        });

        test("should handle duplicate image navigation correctly", () => {
            // Start on second image (middle)
            const secondImg = gallery.querySelector("#img-pos-1") as HTMLElement;
            gallery.setModalImage(secondImg);
            
            // Navigate to next (third image, which is duplicate of first)
            gallery.replaceImage("data-next");
            
            // Should be on third image (position 2), not first image (position 0)
            const thirdImg = gallery.querySelector("#img-pos-2") as HTMLElement;
            expect(gallery.currentImage).toBe(thirdImg);
            expect(gallery.currentImage?.id).toBe("img-pos-2");
        });

        test("should correctly identify target image when clicking on link", () => {
            // Simulate clicking on the link (not directly on img)
            const link = gallery.querySelector(".cast-gallery-modal") as HTMLElement;
            const img = link.querySelector("img") as HTMLElement;
            
            // The handleThumbnailClick should find the img element within the clicked link
            const event = new Event("click");
            Object.defineProperty(event, "target", { value: link, enumerable: true });
            
            // Test the actual handleThumbnailClick method
            (gallery as any).handleThumbnailClick(event);
            expect(gallery.currentImage).toBe(img);
        });

        test("should correctly identify target image when clicking on picture element", () => {
            // Simulate clicking on the picture element (not directly on img)
            const link = gallery.querySelector(".cast-gallery-modal") as HTMLElement;
            const picture = link.querySelector("picture") as HTMLElement;
            const img = link.querySelector("img") as HTMLElement;
            
            const event = new Event("click");
            Object.defineProperty(event, "target", { value: picture, enumerable: true });
            
            // Test the actual handleThumbnailClick method
            (gallery as any).handleThumbnailClick(event);
            expect(gallery.currentImage).toBe(img);
        });

        test("should correctly identify target image when clicking on source element", () => {
            // Simulate clicking on the source element
            const link = gallery.querySelector(".cast-gallery-modal") as HTMLElement;
            const source = link.querySelector("source") as HTMLElement;
            const img = link.querySelector("img") as HTMLElement;
            
            const event = new Event("click");
            Object.defineProperty(event, "target", { value: source, enumerable: true });
            
            // Test the actual handleThumbnailClick method
            (gallery as any).handleThumbnailClick(event);
            expect(gallery.currentImage).toBe(img);
        });
    });
})
