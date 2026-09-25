() => {
    function installCourseOverviewLinks() {
        const root = document.getElementById("le-course-overview");
        if (!root || root.dataset.courseLinksReady === "true") return;
        root.dataset.courseLinksReady = "true";
        root.addEventListener("click", (event) => {
            const button = event.target.closest(".le-overview-node[data-node-id]");
            if (!button) return;
            const nodeId = button.dataset.nodeId;
            const radios = document.querySelectorAll("#le-course-catalog input[type='radio']");
            const buttons = root.querySelectorAll(".le-overview-node[data-node-id]");
            const buttonIndex = Array.from(buttons).indexOf(button);
            const input = Array.from(radios).find((item) => item.value === nodeId)
                || radios[buttonIndex];
            if (!input) return;
            input.click();
            document.getElementById("le-course-content")?.scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
        });
    }

    installCourseOverviewLinks();
    new MutationObserver(installCourseOverviewLinks).observe(document.body, {
        childList: true,
        subtree: true,
    });
}
