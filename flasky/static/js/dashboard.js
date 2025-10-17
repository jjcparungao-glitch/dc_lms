import { showToast } from "./toast.js";
import { Post, Get, Put, Delete, getCookie } from "./api.js";

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

  try {
    const csrf = getCookie("csrf_refresh_token");
    const res = await Post("/auth/refresh", {}, { "X-CSRF-TOKEN": csrf });
    if (res.success) {
      console.log("CSRF token refreshed successfully");
      console.log(res);
    }
  } catch (error) {
    console.error("An error occurred:", error);
  }

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
      if (sidebarTitle)
        sidebarTitle.classList.add("opacity-0", "scale-0", "hidden");
    });
  }
  if (minimizeBtn) {
    minimizeBtn.addEventListener("click", () => {
      sidebar.classList.remove("sidebar-collapsed");
      mainContent.classList.remove("main-collapsed");
      mainContent.classList.add("md:ml-64");
      minimizeBtn.classList.add("hidden");
      if (enlargeBtn) enlargeBtn.classList.remove("hidden");
      if (sidebarTitle)
        sidebarTitle.classList.remove("opacity-0", "scale-0", "hidden");
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

  //KEY MANAGEMENT ELEMENTS

  const openKeyModalBtn = document.getElementById("open-key-modal");
  const keysTableBody = document.getElementById("keys-table-body");
  const emptyKeyState = document.getElementById("emptyKeyState");
  const apiKeyModal = document.getElementById("api-key-modal");
  const keyModalTitle = document.getElementById("key-modal-title");
  const keyForm = document.getElementById("key-form");
  const closeKeyModalBtn = document.getElementById("close-key-modal");
  const saveKeyBtn = document.getElementById("save-key-btn");
  const deleteModal = document.getElementById("delete-modal");
  const confirmDeleteBtn = document.getElementById("confirm-delete");
  const cancelDeleteBtn = document.getElementById("cancel-delete");
  const showGeneratedApiKeyModal =
    document.getElementById("show-api-key-modal");
  const closeApiKeyModalBtnTop = document.getElementById(
    "close-api-key-modal-top"
  );
  const apiKeyDisplay = document.getElementById("new-api-key");
  const copyApiKeyBtn = document.getElementById("copy-api-key");
  const closeApiKeyModalBtnBottom = document.getElementById(
    "close-api-key-modal"
  );

  //API OPERATIONS

  async function fetchApiKeys() {
    try {
      const res = await Get("/api_key/list");
      api_keys = res.data || [];
      console.log("Fetched API keys:", api_keys);

      if (api_keys.length === 0) {
        keysTableBody.classList.add("hidden");
        emptyKeyState.classList.remove("hidden");
        return showToast("No API keys found.", "info");
      }
      keysTableBody.classList.remove("hidden");
      emptyKeyState.classList.add("hidden");
      renderKeys();
      showToast("API keys loaded successfully.", "success");
    } catch (error) {
      showToast("Error loading API keys.", "error");
      console.error("Error fetching API keys:", error);
    }
  }

  async function generateApiKey(keyData) {
    try {
      const res = await Post("/api_key/generate", keyData);
      if (res.success) {
        showToast("API key generated successfully.", "success");
        closeKeyModal();
        await fetchApiKeys();
        if (res.api_key && apiKeyDisplay && showGeneratedApiKeyModal) {
          apiKeyDisplay.textContent = res.api_key;
          showGeneratedApiKeyModal.classList.remove("hidden");
        }
      } else {
        showToast(res.message || "Error generating API key.", "error");
      }
    } catch (error) {
      showToast("Error generating API key.", "error");
      console.error("Error generating API key:", error);
    }
  }

  async function deleteApiKey() {
    if (!selectedKeyId) return;
    try {
      const res = await Delete(`/api_key/delete/${selectedKeyId}`);
      if (res.success) {
        showToast("API key deleted successfully.", "success");
        closeDeleteModal();
        await fetchApiKeys();
        renderKeys();
      } else {
        showToast(res.message || "Error deleting API key.", "error");
      }
    } catch (error) {
      showToast("Error deleting API key.", "error");
      console.error("Error deleting API key:", error);
    }
  }

  async function editKey(keyId, keyData) {
    if (!keyId) return;
    try {
      const res = await Put(`/api_key/edit/${keyId}`, keyData);
      if (res.success) {
        showToast("API key updated successfully.", "success");
        closeKeyModal();
        await fetchApiKeys();
      } else {
        showToast(res.message || "Error updating API key.", "error");
      }
    } catch (error) {
      showToast("Error updating API key.", "error");
      console.error("Error updating API key:", error);
    }
  }

  // RENDERING FUNCTIONS
  function renderKeys() {
    const isMobile = window.innerWidth <= 768;

    // 🧹 Always clear both table and card containers first
    keysTableBody.innerHTML = "";
    document
      .querySelectorAll("#key-cards-container")
      .forEach((el) => el.remove());

    // 🧩 Handle empty state first
    if (api_keys.length === 0) {
      keysTableBody.classList.add("hidden");
      emptyKeyState.classList.remove("hidden");
      return; // ✅ Stop here; don't re-render anything
    }

    // Otherwise, show data
    keysTableBody.classList.remove("hidden");
    emptyKeyState.classList.add("hidden");

    if (isMobile) {
      // 📱 Mobile: Render stacked cards
      const tableContainer = keysTableBody.closest(".overflow-x-auto");
      if (tableContainer) {
        const cardContainer = document.createElement("div");
        cardContainer.className = "grid grid-cols-1 gap-4 py-4 px-2";
        cardContainer.id = "key-cards-container";

        api_keys.forEach((key) => {
          const card = document.createElement("div");
          card.className =
            "bg-white p-4 rounded-lg shadow border border-gray-100 hover:shadow-md transition-shadow";
          card.innerHTML = `
          <div class="flex justify-between items-start mb-3">
            <h3 class="font-semibold text-lg text-gray-800">${escapeHTML(
              key.api_key_id
            )}</h3>
          </div>
          <div class="space-y-2 mb-4">
            <p class="text-sm"><span class="font-medium text-gray-500">ID:</span> ${escapeHTML(
              key.name
            )}</p>
            <p class="text-sm"><span class="font-medium text-gray-500">Role:</span> ${escapeHTML(
              key.created_at
            )}</p>
          </div>
          <div class="flex justify-end space-x-2 border-t pt-3">
            <button class="edit-key-btn text-blue-600 hover:text-blue-800 p-2" data-id="${
              key.api_key_id
            }">
              <i class="fas fa-edit"></i>
            </button>
            <button class="delete-key-btn text-red-600 hover:text-red-800 p-2" data-id="${
              key.api_key_id
            }">
              <i class="fas fa-trash-alt"></i>
            </button>
          </div>
        `;
          cardContainer.appendChild(card);
        });

        // 🧩 Insert before the table container and hide table
        tableContainer.parentNode.insertBefore(cardContainer, tableContainer);
        tableContainer.classList.add("hidden", "md:block");
      }
    } else {
      // 💻 Desktop: Render table rows
      const tableContainer = keysTableBody.closest(".overflow-x-auto");
      if (tableContainer) tableContainer.classList.remove("hidden", "md:block");

      api_keys.forEach((key) => {
        const row = document.createElement("tr");
        row.className = "hover:bg-gray-50";
        row.innerHTML = `
        <td class="px-6 py-4 text-sm font-medium text-gray-900">${escapeHTML(
          key.api_key_id
        )}</td>
        <td class="px-6 py-4 text-sm text-gray-700">${escapeHTML(key.name)}</td>
        <td class="px-6 py-4 text-sm text-gray-700 capitalize">${escapeHTML(
          key.created_at
        )}</td>
        <td class="px-6 py-4 text-center">
          <button class="edit-key-btn text-blue-600 hover:text-blue-800 mx-1" data-id="${
            key.api_key_id
          }">
            <i class="fas fa-edit text-lg"></i>
          </button>
          <button class="delete-key-btn text-red-600 hover:text-red-800 mx-1" data-id="${
            key.api_key_id
          }">
            <i class="fas fa-trash-alt text-lg"></i>
          </button>
        </td>
      `;
        keysTableBody.appendChild(row);
      });
    }

    // ✅ Re-bind events
    addKeyActionListeners();
  }

  function escapeHTML(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function addKeyActionListeners() {
    const editButtons = document.querySelectorAll(".edit-key-btn");
    const deleteButtons = document.querySelectorAll(".delete-key-btn");

    editButtons.forEach((button) => {
      button.addEventListener("click", (event) => {
        const keyId = event.currentTarget.dataset.id;
        openEditKeyModal(keyId);
      });
    });

    deleteButtons.forEach((button) => {
      button.addEventListener("click", (event) => {
        const keyId = event.currentTarget.dataset.id;
        openDeleteModal(keyId);
      });
    });
  }

  window.addEventListener("resize", function () {
    // Debounce the resize event to avoid excessive rendering
    clearTimeout(window.resizeTimer);
    window.resizeTimer = setTimeout(function () {
      if (api_keys && api_keys.length > 0) {
        renderKeys();
      }
    }, 250);
  });

  // MODAL CONTROL

  function openKeyModal() {
    selectedKeyId = null;
    keyForm.reset();
    keyModalTitle.innerHTML =
      '<i class="fas fa-key mr-2"></i> Generate New API Key';
    apiKeyModal.classList.remove("hidden");
  }

  function openEditKeyModal(keyId) {
    const key = api_keys.find((k) => String(k.api_key_id) === String(keyId));
    selectedKeyId = keyId;
    document.getElementById("api-key-name").value = key.name;
    keyModalTitle.innerHTML = '<i class="fas fa-key mr-2"></i> Edit API Key';
    apiKeyModal.classList.remove("hidden");
  }

  function closeKeyModal() {
    apiKeyModal.classList.add("hidden");
    keyForm.reset();
  }

  function openDeleteModal(keyId) {
    selectedKeyId = keyId;
    deleteModal.classList.remove("hidden");
  }

  function closeDeleteModal() {
    deleteModal.classList.add("hidden");
    selectedKeyId = null;
  }

  //FORM SUBMISSION

  async function handleKeyFormSubmit(e) {
    e.preventDefault();

    if (saveKeyBtn) {
      saveKeyBtn.disabled = true;
      saveKeyBtn.textContent = "Saving...";
      saveKeyBtn.classList.add("opacity-50", "cursor-not-allowed");
    }

    try {
      const formData = new FormData(keyForm);
      const keyData = {
        name: formData.get("key_name").trim(),
      };
      if (selectedKeyId) {
        await editKey(selectedKeyId, keyData);
      } else {
        await generateApiKey(keyData);
      }
      selectedKeyId = null;
    } catch (error) {
      showToast("Error processing form data.", "error");
      console.error("Error processing form data:", error);
    } finally {
      if (saveKeyBtn) {
        saveKeyBtn.disabled = false;
        saveKeyBtn.textContent = "Save";
        saveKeyBtn.classList.remove("opacity-50", "cursor-not-allowed");
      }
    }
  }

  // LOGOUT
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".logout-btn");
    if (!btn) return;

    e.preventDefault();
    btn.disabled = true;

    try {
      await Post("/auth/logout");
      showToast("Logged out successfully", "success");
      setTimeout(() => window.location.replace("/login"), 800);
    } catch (err) {
      const msg = err?.response?.data?.message || "Logout failed";
      showToast(msg, "error");
      btn.disabled = false;
    }
  });

  // EVENT LISTENERS
  openKeyModalBtn.addEventListener("click", openKeyModal);
  closeKeyModalBtn.addEventListener("click", closeKeyModal);
  keyForm.addEventListener("submit", handleKeyFormSubmit);
  confirmDeleteBtn.addEventListener("click", deleteApiKey);
  cancelDeleteBtn.addEventListener("click", closeDeleteModal);
  copyApiKeyBtn.addEventListener("click", () => {
    if (apiKeyDisplay) {
      navigator.clipboard.writeText(apiKeyDisplay.textContent).then(() => {
        showToast("API key copied to clipboard!", "success");
      });
    }
  });

  closeApiKeyModalBtnTop.addEventListener("click", () => {
    showGeneratedApiKeyModal.classList.add("hidden");
  });
  closeApiKeyModalBtnBottom.addEventListener("click", () => {
    showGeneratedApiKeyModal.classList.add("hidden");
  });

  //CLOSE MODALS ON OVERLAY CLICK
  [apiKeyModal, deleteModal, showGeneratedApiKeyModal].forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        modal.classList.add("hidden");
      }
    });
  });

  //CLOSE MODALS ON ESCAPE KEY
  [apiKeyModal, deleteModal, showGeneratedApiKeyModal].forEach((modal) => {
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) {
        modal.classList.add("hidden");
      }
    });
  });

  //INITIAL DATA FETCH
  fetchApiKeys();
});
