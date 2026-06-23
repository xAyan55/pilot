// Global PilotPanel JS Actions

document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialize Lucide Icons
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }

  // 2. Mobile Navigation Toggle (Header)
  const mobileToggleBtn = document.querySelector('.mobile-nav-toggle');
  const navLinks = document.querySelector('.nav-links');
  const navBtns = document.querySelector('.nav-btns');

  if (mobileToggleBtn && navLinks) {
    mobileToggleBtn.addEventListener('click', () => {
      navLinks.classList.toggle('active');
      if (navBtns) {
        navBtns.classList.toggle('active');
      }
      
      // Update toggle icon
      const icon = mobileToggleBtn.querySelector('i') || mobileToggleBtn;
      if (icon) {
        if (navLinks.classList.contains('active')) {
          icon.setAttribute('data-lucide', 'x');
        } else {
          icon.setAttribute('data-lucide', 'menu');
        }
        if (typeof lucide !== 'undefined') {
          lucide.createIcons();
        }
      }
    });
  }

  // 3. FAQ Accordion Panels
  const faqQuestions = document.querySelectorAll('.faq-question');
  faqQuestions.forEach(question => {
    question.addEventListener('click', () => {
      const item = question.parentElement;
      const answer = item.querySelector('.faq-answer');
      const isActive = item.classList.contains('active');

      // Close all other open items
      document.querySelectorAll('.faq-item').forEach(otherItem => {
        if (otherItem !== item) {
          otherItem.classList.remove('active');
          const otherAnswer = otherItem.querySelector('.faq-answer');
          if (otherAnswer) otherAnswer.style.maxHeight = null;
        }
      });

      // Toggle current item
      if (isActive) {
        item.classList.remove('active');
        answer.style.maxHeight = null;
      } else {
        item.classList.add('active');
        answer.style.maxHeight = answer.scrollHeight + 'px';
      }
    });
  });

  // 4. Form Password Visibility Toggle
  const pwToggleBtns = document.querySelectorAll('.password-toggle-btn');
  pwToggleBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const input = btn.previousElementSibling;
      const icon = btn.querySelector('i') || btn;
      if (input && input.type) {
        if (input.type === 'password') {
          input.type = 'text';
          icon.setAttribute('data-lucide', 'eye-off');
        } else {
          input.type = 'password';
          icon.setAttribute('data-lucide', 'eye');
        }
        if (typeof lucide !== 'undefined') {
          lucide.createIcons();
        }
      }
    });
  });
});

// 5. Toast Notification System
window.showToast = function(message, type = 'success') {
  let container = document.querySelector('.toast-container');
  
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  
  // Decide icon
  let iconName = 'info';
  if (type === 'success') iconName = 'check-circle';
  if (type === 'error') iconName = 'alert-triangle';
  
  toast.innerHTML = `
    <i data-lucide="${iconName}" style="flex-shrink: 0;"></i>
    <div style="flex-grow: 1;">${message}</div>
  `;
  
  container.appendChild(toast);
  
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
  
  // Slide out and remove
  setTimeout(() => {
    toast.classList.add('fade-out');
    toast.addEventListener('animationend', () => {
      toast.remove();
    });
  }, 4000);
};

// 6. Global AJAX error handling convenience
window.handleFetchResponse = async function(response) {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || 'Something went wrong.');
  }
  return data;
};

// 7. Profile Picture Preview
window.previewProfilePfp = function(input) {
  if (input.files && input.files[0]) {
    const reader = new FileReader();
    reader.onload = function(e) {
      const container = document.querySelector('.profile-pfp-container');
      if (container) {
        container.innerHTML = `<img id="profilePfpImage" src="${e.target.result}" alt="PFP" style="width: 100%; height: 100%; object-fit: cover;">`;
      }
    };
    reader.readAsDataURL(input.files[0]);
  }
};

// 8. Update User Profile Info
window.handleUpdateProfile = async function(event) {
  event.preventDefault();
  const form = event.target;
  const usernameInput = document.getElementById('profileUsername');
  const emailInput = document.getElementById('profileEmail');
  const fileInput = document.getElementById('profilePfpInput');

  if (!usernameInput || !emailInput) return;

  const formData = new FormData();
  formData.append('username', usernameInput.value);
  formData.append('email', emailInput.value);

  if (fileInput && fileInput.files[0]) {
    formData.append('pfp', fileInput.files[0]);
  }

  showToast('Updating profile details...', 'info');

  try {
    const response = await fetch('/api/profile/update', {
      method: 'POST',
      body: formData
    });
    const data = await window.handleFetchResponse(response);

    // Update avatar displays across page
    if (data.pfp) {
      // 1. Sidebar Avatar
      const sidebarAvatar = document.querySelector('.db-sidebar-footer .db-user-avatar');
      if (sidebarAvatar) {
        sidebarAvatar.innerHTML = `<img id="sidebarPfp" src="${data.pfp}" alt="PFP" style="width: 100%; height: 100%; object-fit: cover;">`;
      }
      
      // 2. Profile Preview Avatar (if it wasn't there before)
      const profileContainer = document.querySelector('.profile-pfp-container');
      if (profileContainer) {
        profileContainer.innerHTML = `<img id="profilePfpImage" src="${data.pfp}" alt="PFP" style="width: 100%; height: 100%; object-fit: cover;">`;
      }
    }

    // Update username display in sidebar footer
    const sidebarName = document.querySelector('.db-sidebar-footer .db-user-name');
    if (sidebarName) {
      sidebarName.textContent = data.username;
      sidebarName.title = data.username;
    }

    showToast(data.message, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// 9. Update Account Password
window.handleUpdatePassword = async function(event) {
  event.preventDefault();
  const currentPassword = document.getElementById('profileCurrentPassword').value;
  const newPassword = document.getElementById('profileNewPassword').value;
  const confirmPassword = document.getElementById('profileConfirmPassword').value;

  if (newPassword !== confirmPassword) {
    showToast('New passwords do not match.', 'error');
    return;
  }

  showToast('Updating password...', 'info');

  try {
    const response = await fetch('/api/profile/update-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword
      })
    });
    const data = await window.handleFetchResponse(response);
    showToast(data.message, 'success');
    event.target.reset();
  } catch (err) {
    showToast(err.message, 'error');
  }
};
