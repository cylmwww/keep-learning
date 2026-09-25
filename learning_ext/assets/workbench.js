() => {
    const panel = document.getElementById("le-assistant-panel");
    const openButton = document.getElementById("le-assistant-open");
    const closeButton = document.getElementById("le-assistant-close");
    if (!panel || !openButton || !closeButton || document.getElementById("le-assistant-dialog")) return;

    const dialog = document.createElement("dialog");
    dialog.id = "le-assistant-dialog";
    dialog.setAttribute("aria-label", "AI 问答助手");
    panel.before(dialog);
    dialog.append(panel);

    let opener = openButton;
    const open = event => {
        if (dialog.open) return;
        opener = event.currentTarget;
        dialog.showModal();
        panel.querySelector("#le-assistant-input textarea")?.focus();
    };
    openButton.addEventListener("click", open);
    document.getElementById("le-assistant-fab")?.addEventListener("click", open);
    closeButton.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", event => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right ||
            event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
    dialog.addEventListener("close", () => opener.focus({preventScroll: true}));
}
