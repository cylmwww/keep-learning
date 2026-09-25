() => {
    const navigation = document.getElementById("learning-navigation");
    const sidebar = navigation?.querySelector(":scope > .tab-nav");
    if (!navigation || !sidebar || document.getElementById("le-navigation-toggle")) return;

    const icon = (name) => {
        const paths = {
            "首页": '<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3z"/>',
            "我的课程": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 5.5v15M7 20h13M8 7h8M8 10h6"/>',
            "课程管理": '<path d="M4 6.5h16v13H4z"/><path d="M8 3.5h8v3H8zM8 11h8M8 15h5"/>',
            "知识问答": '<path d="M5 5.5h14A2.5 2.5 0 0 1 21.5 8v7a2.5 2.5 0 0 1-2.5 2.5H11l-5 3v-3.5A2.5 2.5 0 0 1 3.5 15V8A2.5 2.5 0 0 1 5 5.5z"/><path d="M8 10h8M8 13h5"/>',
            "间隔复习": '<path d="M20 11a8 8 0 1 1-2.34-5.66"/><path d="M20 4v7h-7"/><path d="M12 8v4l2.5 1.5"/>',
            "查漏测验": '<path d="M6 3.5h12A1.5 1.5 0 0 1 19.5 5v14A1.5 1.5 0 0 1 18 20.5H6A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 6 3.5z"/><path d="m8 12 2.2 2.2L16 8.5M8 6.5h8"/>',
            "资料库": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 5.5v15M8 7h8M8 10h6"/>',
            "模型配置": '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.64 5.64l2.12 2.12M16.24 16.24l2.12 2.12M18.36 5.64l-2.12 2.12M7.76 16.24l-2.12 2.12"/><circle cx="12" cy="12" r="4"/>',
            "使用指南": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9a2.5 2.5 0 1 1 4.2 1.8c-1 .9-1.8 1.3-1.8 2.7M12 16.5h.01"/>',
            "帮助": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9a2.5 2.5 0 1 1 4.2 1.8c-1 .9-1.8 1.3-1.8 2.7M12 16.5h.01"/>',
        };
        return paths[name] || paths["帮助"];
    };

    const secondary = new Set(["模型配置", "使用指南", "帮助"]);
    sidebar.querySelectorAll("button").forEach((button) => {
        const label = button.textContent.trim();
        if (!label || button.querySelector(".le-nav-icon")) return;
        if (secondary.has(label)) button.classList.add("le-nav-secondary");
        button.innerHTML = `<span class="le-nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icon(label)}</svg></span><span class="le-nav-label">${label}</span>`;
    });

    const toggle = document.createElement("button");
    toggle.id = "le-navigation-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-controls", "learning-navigation-sidebar");
    toggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
    navigation.append(toggle);
    sidebar.id = "learning-navigation-sidebar";

    const storageKey = "learning-agent-sidebar-collapsed";
    let collapsed = false;
    try {
        const saved = localStorage.getItem(storageKey);
        if (saved !== null) collapsed = saved === "true";
    } catch {}

    const render = () => {
        navigation.classList.toggle("le-sidebar-collapsed", collapsed);
        toggle.setAttribute("aria-expanded", String(!collapsed));
        toggle.setAttribute("aria-label", collapsed ? "展开侧栏" : "收起侧栏");
        toggle.title = collapsed ? "展开导航侧栏" : "收起导航侧栏";
        window.dispatchEvent(new Event("resize"));
    };
    toggle.addEventListener("click", () => {
        collapsed = !collapsed;
        render();
        try {
            localStorage.setItem(storageKey, String(collapsed));
        } catch {}
    });
    render();

    const backToTop = document.createElement("button");
    backToTop.id = "le-back-to-top";
    backToTop.type = "button";
    backToTop.title = "返回顶部";
    backToTop.setAttribute("aria-label", "返回顶部");
    backToTop.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 15 6-6 6 6"/></svg>';
    backToTop.hidden = true;
    document.body.append(backToTop);

    const scrollTargets = () => {
        const page = ["learning-home-tab", "learning-course-tab"]
            .map(id => document.getElementById(id))
            .find(element => element && element.getClientRects().length > 0);
        if (!page) return [];
        return [page, ...(page.id === "learning-course-tab"
            ? [document.getElementById("le-course-main")] : []), document.scrollingElement]
            .filter(Boolean);
    };
    let frame = 0;
    const updateBackToTop = () => {
        if (frame) return;
        frame = requestAnimationFrame(() => {
            frame = 0;
            backToTop.hidden = !scrollTargets().some(element => element.scrollTop > 240);
        });
    };
    backToTop.addEventListener("click", () => {
        const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
        scrollTargets().forEach(element => element.scrollTo({top: 0, behavior}));
    });
    document.addEventListener("scroll", updateBackToTop, {capture: true, passive: true});
    window.addEventListener("resize", updateBackToTop);
    new MutationObserver(updateBackToTop).observe(navigation, {
        subtree: true, attributes: true, attributeFilter: ["style", "class", "hidden"],
    });
    updateBackToTop();
}
