
export function showToast(message, type = "info") {
  let bgColor;

  switch (type) {
    case "success":
      bgColor = "linear-gradient(to right, #00b09b, #96c93d)"; // green
      break;
    case "error":
      bgColor = "linear-gradient(to right, #ff416c, #ff4b2b)"; // red
      break;
    case "warning":
      bgColor = "linear-gradient(to right, #f7971e, #ffd200)"; // orange
      break;
    default:
      bgColor = "linear-gradient(to right, #00c6ff, #0072ff)"; // blue
  }

  Toastify({
    text: message,
    duration: 3000,
    gravity: "top", // 'top' or 'bottom'
    position: "center", // 'left', 'center', 'right'
    style: {
      background: bgColor,

    },
    close: true,
    stopOnFocus: true,
  }).showToast();
}