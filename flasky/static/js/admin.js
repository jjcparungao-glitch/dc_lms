import { showToast } from "./toast.js";
import { Post, Get, Put, Delete, Patch } from "./api.js";

let selectedUserId = null;
let users = [];

document.addEventListener("DOMContentLoaded", async() => {
  // --- Sidebar functionality ---
  const sidebar = document.getElementById("sidebar");
  const enlargeBtn = document.getElementById("expand-sidebar");
  const minimizeBtn = document.getElementById("collapse-sidebar");
  const sidebarTitle = document.getElementById("sidebartitle");
  const sections = document.querySelectorAll("main section");
  const mainContent = document.getElementById("main-content");
  const navButtons = document.querySelectorAll(".sidebar-btn");
  const reportsBtn = document.querySelector(
    '[data-target="reports-analytics"]'
  );

  // Mobile menu elements
  const mobileMenuBtn = document.getElementById("mobile-menu-btn");
  const mobileMenu = document.getElementById("mobile-menu");
  const mobileNavButtons = document.querySelectorAll(".mobile-nav-btn");

  try {
    await Post("/auth/refresh");
    // Optionally, handle UI updates or errors here
    console.log("Access token refreshed on reload.");
  } catch (error) {
    console.warn("Token refresh failed:", error);
    // Optionally, redirect to login if refresh fails
    window.location.href = "/login";
  }
  // Toggle mobile menu
  if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener("click", () => {
      mobileMenu.classList.toggle("visible");
      mobileMenu.classList.toggle("hidden");
    });
  }

  // Mobile nav buttons functionality
  mobileNavButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.dataset.target;

      // Hide mobile menu after selection on small screens
      mobileMenu.classList.add("hidden");
      mobileMenu.classList.remove("visible");

      // Show selected section
      sections.forEach((section) => section.classList.add("hidden"));
      const targetSection = document.getElementById(targetId);
      if (targetSection) targetSection.classList.remove("hidden");

      // Highlight selected button in mobile nav
      mobileNavButtons.forEach((btn) =>
        btn.classList.remove("bg-gray-200", "text-red-700", "font-semibold")
      );
      button.classList.add("bg-gray-200", "text-red-700", "font-semibold");

      // Also update the desktop sidebar selection
      navButtons.forEach((btn) => {
        if (btn.dataset.target === targetId) {
          btn.classList.add("bg-gray-200", "text-red-700", "font-semibold");
        } else {
          btn.classList.remove("bg-gray-200", "text-red-700", "font-semibold");
        }
      });
    });
  });

  // Reports button click event
  if (reportsBtn) {
    reportsBtn.addEventListener("click", () => {
      // Load Chart.js if not already loaded
      if (!window.Chart) {
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/chart.js";
        script.onload = () => {
          // Then load our reports module
          import("./reports.js").catch((err) =>
            console.error("Failed to load reports module:", err)
          );
        };
        document.head.appendChild(script);
      } else {
        // Chart.js already loaded, just load our reports
        import("./reports.js").catch((err) =>
          console.error("Failed to load reports module:", err)
        );
      }
    });
  }

  // Sidebar collapse/expand
  enlargeBtn.addEventListener("click", () => {
    sidebar.classList.add("sidebar-collapsed");
    mainContent.classList.add("main-collapsed");
    mainContent.classList.remove("md:ml-64");
    enlargeBtn.classList.add("hidden");
    minimizeBtn.classList.remove("hidden");
    sidebarTitle.classList.add("opacity-0", "scale-0", "hidden");
  });

  minimizeBtn.addEventListener("click", () => {
    sidebar.classList.remove("sidebar-collapsed");
    mainContent.classList.remove("main-collapsed");
    mainContent.classList.add("md:ml-64");
    minimizeBtn.classList.add("hidden");
    enlargeBtn.classList.remove("hidden");
    sidebarTitle.classList.remove("opacity-0", "scale-0", "hidden");
  });

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

  // --- User Management Elements ---
  const userTableBody = document.getElementById("user-table-body");
  const emptyUserState = document.getElementById("emptyUserState");
  const userModal = document.getElementById("user-modal");
  const userForm = document.getElementById("user-form");
  const userModalTitle = document.getElementById("user-modal-title");
  const deleteModal = document.getElementById("delete-modal");
  const openAddUserBtn = document.getElementById("open-add-user");
  const closeUserModalBtn = document.getElementById("close-user-modal");
  const cancelDeleteBtn = document.getElementById("cancel-delete");
  const confirmDeleteBtn = document.getElementById("confirm-delete");
  const statusModal = document.getElementById("status-modal");
  const cancelStatusChangeBtn = document.getElementById("cancel-status-change");
  const confirmStatusChangeBtn = document.getElementById(
    "confirm-status-change"
  );

  // ===== API OPERATIONS =====

  async function fetchUsers() {
    try {
      const res = await Get("/admin/users");
      users = res.data || [];
      if (users.length === 0) {
        userTableBody.classList.add("hidden");
        emptyUserState.classList.remove("hidden");
        return showToast("No users found", "warning");
      }
      renderUsers();
      showToast("Users loaded successfully", "success");
    } catch (error) {
      showToast(
        error.response?.data?.message || "Failed to load users",
        "error"
      );
      console.error("Error fetching users:", error);
    }
  }

  async function createUser(userData) {
    try {
      const res = await Post("/admin/users/create", userData);
      if (res.success) {
        showToast("User created successfully", "success");
        closeUserModal();
        fetchUsers();
      } else showToast(res.message || "Failed to create user", "error");
    } catch (error) {
      showToast(
        error.response?.data?.message || "Failed to create user",
        "error"
      );
      console.error(error);
    }
  }

  async function updateUser(userId, userData) {
    if (!userId) return;
    try {
      const res = await Put(`/admin/users/update/${userId}`, userData);
      if (res.success) {
        showToast("User updated successfully", "success");
        closeUserModal();
        fetchUsers();
      } else showToast(res.message || "Failed to update user", "error");
    } catch (error) {
      showToast(
        error.response?.data?.message || "Failed to update user",
        "error"
      );
      console.error(error);
    }
  }

  async function deleteUser() {
    if (!selectedUserId) return;
    try {
      const res = await Delete(`/admin/users/delete/${selectedUserId}`);
      if (res.success) {
        showToast("User deleted successfully", "success");
        closeDeleteModal();
        fetchUsers();
      } else showToast(res.message || "Failed to delete user", "error");
    } catch (error) {
      showToast(
        error.response?.data?.message || "Failed to delete user",
        "error"
      );
      console.error(error);
    }
  }

  async function updateUserStatus(userId, isActive) {
    try {
      const res = await Patch(`/admin/users/status/${userId}`, {
        status: isActive ? "active" : "inactive",
      });
      if (res.success) {
        showToast(
          `User ${isActive ? "activated" : "deactivated"} successfully`,
          "success"
        );
        fetchUsers();
      } else showToast(res.message || "Failed to update status", "error");
    } catch (error) {
      showToast(
        error.response?.data?.message || "Failed to update user status",
        "error"
      );
      console.error(error);
    }
  }
  async function loadPeakHours() {
    try {
      const peakHoursContainer = document.getElementById("peak-hours-list");
      if (!peakHoursContainer) return;

      const response = await fetch("/api/admin/reports/peak-hours", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
      });

      const data = await response.json();

      if (!data.success || !data.peak_hours || data.peak_hours.length === 0) {
        peakHoursContainer.innerHTML = `
        <div class="text-center p-4 text-gray-500">
          No activity data available
        </div>
      `;
        return;
      }

      // Get the maximum count for scaling the bars
      const maxCount = Math.max(...data.peak_hours.map((h) => h.count));

      // Build HTML for peak hours
      const peakHoursHTML = data.peak_hours
        .map((item) => {
          const percentage = Math.round((item.count / maxCount) * 100);

          return `
        <div class="mb-3">
          <div class="flex justify-between mb-1">
            <div class="text-lg font-bold text-red-600">${item.hour}</div>
            <div class="text-gray-700">${item.count} tasks</div>
          </div>
          <div class="w-full bg-gray-200 rounded-full h-2.5">
            <div class="bg-red-600 h-2.5 rounded-full" style="width: ${percentage}%"></div>
          </div>
        </div>
      `;
        })
        .join("");

      peakHoursContainer.innerHTML = peakHoursHTML;
    } catch (error) {
      console.error("Error loading peak hours:", error);
      const peakHoursContainer = document.getElementById("peak-hours-list");
      if (peakHoursContainer) {
        peakHoursContainer.innerHTML = `
        <div class="text-center p-4 text-red-500">
          Error loading peak hours data
        </div>
      `;
      }
    }
  }
  // ===== UI RENDERING =====

  function renderUsers() {
    userTableBody.innerHTML = "";

    if (users.length === 0) {
      userTableBody.classList.add("hidden");
      emptyUserState.classList.remove("hidden");
      return;
    }

    userTableBody.classList.remove("hidden");
    emptyUserState.classList.add("hidden");

    // Check if we're on mobile (screen width less than 768px)
    const isMobile = window.innerWidth < 768;

    if (isMobile) {
      // Mobile stacked cards view
      const tableContainer = userTableBody.closest(".overflow-x-auto");
      if (tableContainer) {
        const cardContainer = document.createElement("div");
        cardContainer.className = "grid grid-cols-1 gap-4 py-4 px-2";
        cardContainer.id = "user-cards-container";

        users.forEach((user) => {
          const card = document.createElement("div");
          card.className =
            "bg-white p-4 rounded-lg shadow border border-gray-100 hover:shadow-md transition-shadow";

          const statusBadge =
            user.status === "active"
              ? '<span class="px-2 py-1 bg-green-100 text-green-800 rounded-full text-xs">Active</span>'
              : '<span class="px-2 py-1 bg-red-100 text-red-800 rounded-full text-xs">Inactive</span>';

          card.innerHTML = `
          <div class="flex justify-between items-start mb-3">
            <h3 class="font-semibold text-lg text-gray-800">${escapeHTML(
              user.full_name
            )}</h3>
            ${statusBadge}
          </div>
          <div class="space-y-2 mb-4">
            <p class="text-sm"><span class="font-medium text-gray-500">ID:</span> ${escapeHTML(
              user.id
            )}</p>
            <p class="text-sm"><span class="font-medium text-gray-500">Email:</span> ${escapeHTML(
              user.email
            )}</p>
            <p class="text-sm"><span class="font-medium text-gray-500">Role:</span> <span class="capitalize">${escapeHTML(
              user.role
            )}</span></p>
          </div>
          <div class="flex justify-end space-x-2 border-t pt-3">
            <button class="edit-user-btn text-blue-600 hover:text-blue-800 p-2" data-id="${
              user.id
            }">
              <i class="fas fa-edit"></i>
            </button>
            <button class="status-user-btn text-${
              user.status === "active" ? "green" : "gray"
            }-600 hover:text-${
            user.status === "active" ? "green" : "gray"
          }-800 p-2" data-id="${user.id}">
              <i class="fas fa-${
                user.status === "active" ? "toggle-on" : "toggle-off"
              }"></i>
            </button>
            <button class="delete-user-btn text-red-600 hover:text-red-800 p-2" data-id="${
              user.id
            }">
              <i class="fas fa-trash-alt"></i>
            </button>
          </div>
        `;

          cardContainer.appendChild(card);
        });

        // Replace table with cards
        const oldCards = document.getElementById("user-cards-container");
        if (oldCards) oldCards.remove();

        tableContainer.parentNode.insertBefore(cardContainer, tableContainer);
        tableContainer.classList.add("hidden", "md:block");
      }
    } else {
      // Desktop table view - show table and remove cards if they exist
      const tableContainer = userTableBody.closest(".overflow-x-auto");
      const cardContainer = document.getElementById("user-cards-container");

      if (tableContainer) tableContainer.classList.remove("hidden", "md:block");
      if (cardContainer) cardContainer.remove();

      // Standard table rendering
      users.forEach((user) => {
        const row = document.createElement("tr");
        row.className = "hover:bg-gray-50";

        const statusBadge =
          user.status === "active"
            ? '<span class="px-2 py-1 bg-green-100 text-green-800 rounded-full text-xs">Active</span>'
            : '<span class="px-2 py-1 bg-red-100 text-red-800 rounded-full text-xs">Inactive</span>';

        row.innerHTML = `
        <td class="px-6 py-4 text-sm font-medium text-gray-900">${escapeHTML(
          user.id
        )}</td>
        <td class="px-6 py-4 text-sm text-gray-700">${escapeHTML(
          user.full_name
        )}</td>
        <td class="px-6 py-4 text-sm text-gray-700">${escapeHTML(
          user.email
        )}</td>
        <td class="px-6 py-4 text-sm text-gray-700 capitalize">${escapeHTML(
          user.role
        )}</td>
        <td class="px-6 py-4 text-left">${statusBadge}</td>
        <td class="px-6 py-4 text-center">
          <button class="edit-user-btn text-blue-600 hover:text-blue-800 mx-1" data-id="${
            user.id
          }">
            <i class="fas fa-edit text-lg"></i>
          </button>
          <button class="status-user-btn text-${
            user.status === "active" ? "green" : "gray"
          }-600 hover:text-${
          user.status === "active" ? "green" : "gray"
        }-800 mx-1" data-id="${user.id}">
            <i class="fas fa-${
              user.status === "active" ? "toggle-on" : "toggle-off"
            } text-lg"></i>
          </button>
          <button class="delete-user-btn text-red-600 hover:text-red-800 mx-1" data-id="${
            user.id
          }">
            <i class="fas fa-trash-alt text-lg"></i>
          </button>
        </td>
      `;

        userTableBody.appendChild(row);
      });
    }

    addUserActionListeners();
  }

  // Update addUserActionListeners function to handle both table and cards
  function addUserActionListeners() {
    document.querySelectorAll(".edit-user-btn").forEach((btn) => {
      btn.addEventListener("click", () => editUser(btn.dataset.id));
    });
    document.querySelectorAll(".delete-user-btn").forEach((btn) => {
      btn.addEventListener("click", () =>
        openDeleteConfirmation(btn.dataset.id)
      );
    });
    document.querySelectorAll(".status-user-btn").forEach((btn) => {
      btn.addEventListener("click", () =>
        openStatusChangeConfirmation(btn.dataset.id)
      );
    });
  }

  // Add window resize listener to handle switching between views
  window.addEventListener("resize", function () {
    // Debounce the resize event to avoid excessive rendering
    clearTimeout(window.resizeTimer);
    window.resizeTimer = setTimeout(function () {
      if (users && users.length > 0) {
        renderUsers();
      }
    }, 250);
  });
  function escapeHTML(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // ===== MODAL CONTROL =====
  function openAddUserModal() {
    selectedUserId = null;
    userForm.reset();
    userModalTitle.innerHTML = '<i class="fas fa-user-plus mr-2"></i> Add User';
    document.getElementById("user-password").required = true;
    userModal.classList.remove("hidden");
  }

  function editUser(userId) {
    const user = users.find((u) => u.id == userId);
    if (!user) return;

    selectedUserId = userId;
    document.getElementById("user-id").value = user.id;
    document.getElementById("user-fullname").value = user.full_name;
    document.getElementById("user-email").value = user.email;
    document.getElementById("user-role").value = user.role;
    document.getElementById("user-password").required = false;

    userModalTitle.innerHTML =
      '<i class="fas fa-user-edit mr-2"></i> Edit User';
    userModal.classList.remove("hidden");
  }

  function closeUserModal() {
    userModal.classList.add("hidden");
    userForm.reset();
  }

  function openDeleteConfirmation(userId) {
    selectedUserId = userId;
    deleteModal.classList.remove("hidden");
  }

  function closeDeleteModal() {
    deleteModal.classList.add("hidden");
    selectedUserId = null;
  }

  function openStatusChangeConfirmation(userId) {
    selectedUserId = userId;
    statusModal.classList.remove("hidden");
  }

  function closeStatusChangeModal() {
    statusModal.classList.add("hidden");
    selectedUserId = null;
  }

  // ===== FORM SUBMISSION =====
  async function handleUserFormSubmit(e) {
    e.preventDefault();

    const submitBtn = userForm.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.classList.add("opacity-50", "cursor-not-allowed");
    }

    try {
      const formData = new FormData(userForm);
      const userData = {
        full_name: formData.get("full_name"),
        email: formData.get("email"),
        role: formData.get("role"),
      };

      const password = formData.get("password");
      if (password && password.trim() !== "") userData.password = password;

      if (selectedUserId) {
        await updateUser(selectedUserId, userData);
      } else {
        if (!userData.password) {
          showToast("Password is required", "error");
          return;
        }
        await createUser(userData);
      }
    } catch (err) {
      console.error("Error submitting user form:", err);
      showToast("Something went wrong. Please try again.", "error");
    } finally {

      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.classList.remove("opacity-50", "cursor-not-allowed");
      }
    }
  }

  // ===== LOGOUT =====
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

  // ===== EVENT BINDINGS =====
  openAddUserBtn.addEventListener("click", openAddUserModal);
  closeUserModalBtn.addEventListener("click", closeUserModal);
  userForm.addEventListener("submit", handleUserFormSubmit);
  cancelDeleteBtn.addEventListener("click", closeDeleteModal);
  confirmDeleteBtn.addEventListener("click", deleteUser);
  cancelStatusChangeBtn.addEventListener("click", closeStatusChangeModal);
  confirmStatusChangeBtn.addEventListener("click", () => {
    const currentUser = users.find((u) => u.id == selectedUserId);
    if (currentUser) {
      const newStatus = currentUser.status === "active" ? "inactive" : "active";
      updateUserStatus(selectedUserId, newStatus === "active");
      closeStatusChangeModal();
    }
  });

  // Close modals on overlay click
  [userModal, deleteModal, statusModal].forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.classList.add("hidden");
    });
  });

  // Close modals on ESC
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      [userModal, deleteModal, statusModal].forEach((modal) =>
        modal.classList.add("hidden")
      );
    }
  });

  // Load users initially
  fetchUsers();
  loadPeakHours();
});