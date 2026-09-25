() => {
    const translations = __TRANSLATIONS__;
    const dynamicIds = __DYNAMIC_IDS__;
    const roots = [document.getElementById("chat-tab"), document.getElementById("indices-tab")].filter(Boolean);
    const translate = text => translations[text] || text;
    const updateText = (element, dynamic = false) => {
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            const original = node.textContent;
            const trimmed = original.trim();
            let translated = translate(trimmed);
            if (dynamic) translated = translated.replace(/\b(\d+) chunks\b/g, "$1 个内容片段")
                .replace(/\b(\d+) (text|table|image|thumbnail)\b/g, (_, count, type) => `${count} 个${translate(type)}`);
            if (translated !== trimmed) node.textContent = original.replace(trimmed, translated);
        }
    };
    const refresh = () => {
        for (const root of roots) {
            for (const element of root.querySelectorAll("button, label, th, [role='columnheader']")) {
                if (element.closest("#main-chat-bot, #html-info-panel, [role='option'], td")) continue;
                if (element.querySelector("table")) continue;
                updateText(element);
            }
            for (const element of root.querySelectorAll("[placeholder], [title], [aria-label]")) {
                if (element.closest("#html-info-panel")) continue;
                for (const attr of ["placeholder", "title", "aria-label"]) {
                    const value = element.getAttribute(attr);
                    if (value && translate(value) !== value) element.setAttribute(attr, translate(value));
                }
            }
        }
        for (const id of dynamicIds) {
            const element = document.getElementById(id);
            if (element) updateText(element, true);
        }
    };
    let scheduled = false;
    const observer = new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => {
            scheduled = false;
            observer.disconnect();
            refresh();
            observe();
        });
    });
    const observe = () => roots.forEach(root => observer.observe(root, {
        childList: true, subtree: true, characterData: true,
        attributes: true, attributeFilter: ["placeholder", "title", "aria-label"]
    }));
    refresh();
    observe();
}
