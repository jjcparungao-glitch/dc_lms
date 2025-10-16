let api_keys = [];
let selectedKeyId = null;
document.addEventListener("DOMContentLoaded", async () => {
  // --- Sidebar functionality ---
  const sidebar = document.getElementById("sidebar");
  const enlargeBtn = document.getElementById("expand-sidebar");
  const minimizeBtn = document.getElementById("collapse-sidebar");
  const sidebarTitle = document.getElementById("sidebartitle");
  const sections = document.querySelectorAll("main section");
  const mainContent = document.getElementById("main-content");
  const navButtons = document.querySelectorAll(".sidebar-btn");
  const mobileMenuBtn = document.getElementById("mobile-menu-btn");
  const mobileMenu = document.getElementById("mobile-menu");
  const mobileNavButtons = document.querySelectorAll(".mobile-nav-btn");



  // Toggle mobile menu
  if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener("click", () => {
      if (!mobileMenu) return;
      mobileMenu.classList.toggle("visible");
      mobileMenu.classList.toggle("hidden");
    });
  }

  // Mobile nav buttons functionality
  mobileNavButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.dataset.target;
      if (mobileMenu) {
        mobileMenu.classList.add("hidden");
        mobileMenu.classList.remove("visible");
      }
      sections.forEach((section) => section.classList.add("hidden"));
      const targetSection = document.getElementById(targetId);
      if (targetSection) targetSection.classList.remove("hidden");
      mobileNavButtons.forEach((btn) =>
        btn.classList.remove("bg-gray-200", "text-red-700", "font-semibold")
      );
      button.classList.add("bg-gray-200", "text-red-700", "font-semibold");
      navButtons.forEach((btn) => {
        if (btn.dataset.target === targetId) {
          btn.classList.add("bg-gray-200", "text-red-700", "font-semibold");
        } else {
          btn.classList.remove("bg-gray-200", "text-red-700", "font-semibold");
        }
      });
    });
  });

  // Sidebar collapse/expand
  if (enlargeBtn) {
    enlargeBtn.addEventListener("click", () => {
      sidebar.classList.add("sidebar-collapsed");
      mainContent.classList.add("main-collapsed");
      mainContent.classList.remove("md:ml-64");
      enlargeBtn.classList.add("hidden");
      if (minimizeBtn) minimizeBtn.classList.remove("hidden");
      if (sidebarTitle) sidebarTitle.classList.add("opacity-0", "scale-0", "hidden");
    });
  }
  if (minimizeBtn) {
    minimizeBtn.addEventListener("click", () => {
      sidebar.classList.remove("sidebar-collapsed");
      mainContent.classList.remove("main-collapsed");
      mainContent.classList.add("md:ml-64");
      minimizeBtn.classList.add("hidden");
      if (enlargeBtn) enlargeBtn.classList.remove("hidden");
      if (sidebarTitle) sidebarTitle.classList.remove("opacity-0", "scale-0", "hidden");
    });
  }

  // --- Default Dashboard View ---
  const dashboardButton = document.getElementById("dashboard-btn");
  const dashboardSection = document.getElementById("dashboard");
  if (dashboardButton && dashboardSection) {
    dashboardButton.classList.add(
      "bg-gray-200",
      "text-red-700",
      "font-semibold"
    );
    dashboardSection.classList.remove("hidden");
  }

  // --- Navigation buttons ---
  navButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.dataset.target;
      sections.forEach((section) => section.classList.add("hidden"));
      const targetSection = document.getElementById(targetId);
      if (targetSection) targetSection.classList.remove("hidden");
      navButtons.forEach((btn) =>
        btn.classList.remove("bg-gray-200", "text-red-700", "font-semibold")
      );
      button.classList.add("bg-gray-200", "text-red-700", "font-semibold");
    });
  });


});
