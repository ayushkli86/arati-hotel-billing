/* Menu board Alpine component.
   Shared by /menu (public, read-only) and /admin/menu (full editing).
   All rendering uses x-text / x-bind so item names can never inject markup. */
(function () {
  function slugify(value) {
    return String(value || '')
      .normalize('NFKD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'item';
  }

  function formatPrice(value) {
    var num = Number(value) || 0;
    return num % 1 === 0
      ? num.toLocaleString('en-US')
      : num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function fileToJpegBlob(file, maxW, quality) {
    maxW = maxW || 1000;
    quality = quality == null ? 0.85 : quality;
    var url = URL.createObjectURL(file);
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        try {
          var scale = Math.min(1, maxW / (img.naturalWidth || maxW));
          var w = Math.max(1, Math.round(img.naturalWidth * scale));
          var h = Math.max(1, Math.round(img.naturalHeight * scale));
          var canvas = document.createElement('canvas');
          canvas.width = w;
          canvas.height = h;
          canvas.getContext('2d').drawImage(img, 0, 0, w, h);
          canvas.toBlob(function (blob) { URL.revokeObjectURL(url); resolve(blob); }, 'image/jpeg', quality);
        } catch (error) { URL.revokeObjectURL(url); reject(error); }
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('That file could not be read as an image.')); };
      img.src = url;
    });
  }

  function emptyForm() {
    return { name: '', slug: '', category: '', description: '', price: '', image: '', available: true };
  }

  window.menuBoard = function (items, options) {
    options = options || {};
    return {
      items: Array.isArray(items) ? items : [],
      isAdmin: !!options.isAdmin,
      csrf: options.csrf || '',
      q: '',
      category: 'all',
      availability: options.defaultAvailability || 'all',

      modalOpen: false,
      editingId: null,
      saving: false,
      uploading: false,
      errors: {},
      form: emptyForm(),
      slugTouched: false,
      useImageUrl: false,
      dragOver: false,

      init: function () {
        var self = this;
        this.$watch('form.name', function (value) {
          if (!self.slugTouched) self.form.slug = slugify(value);
        });
      },

      /* ---- derived data ---- */
      categories: function () {
        var seen = [], out = [];
        this.items.forEach(function (i) { if (seen.indexOf(i.category) < 0) { seen.push(i.category); out.push(i.category); } });
        return out.sort();
      },
      filtered: function () {
        var term = this.q.trim().toLowerCase();
        var availability = this.availability;
        var category = this.category;
        return this.items.filter(function (i) {
          if (category !== 'all' && i.category !== category) return false;
          if (availability === 'available' && !i.available) return false;
          if (availability === 'unavailable' && i.available) return false;
          if (!term) return true;
          return (i.name || '').toLowerCase().indexOf(term) >= 0
            || (i.slug || '').toLowerCase().indexOf(term) >= 0
            || (i.category || '').toLowerCase().indexOf(term) >= 0
            || (i.description || '').toLowerCase().indexOf(term) >= 0;
        });
      },
      grouped: function () {
        var order = [], buckets = {};
        this.items.forEach(function (i) {
          if (!Object.prototype.hasOwnProperty.call(buckets, i.category)) {
            buckets[i.category] = [];
            order.push(i.category);
          }
        });
        this.filtered().forEach(function (i) { buckets[i.category].push(i); });
        Object.keys(buckets).forEach(function (c) {
            buckets[c].sort(function (a, b) { return (a.sort_order || 0) - (b.sort_order || 0); });
        });
        return order
          .filter(function (c) { return buckets[c].length; })
          .map(function (c) { return { category: c, items: buckets[c] }; });
      },
      matching: function () { return this.filtered().length; },
      total: function () { return this.items.length; },
      formatPrice: formatPrice,

      /* ---- CRUD ---- */
      openAdd: function () {
        this.form = emptyForm();
        this.form.category = this.category !== 'all' ? this.category : (this.categories()[0] || '');
        this.editingId = null;
        this.errors = {};
        this.slugTouched = false;
        this.useImageUrl = false;
        this.modalOpen = true;
        this.focusModal();
      },
      openEdit: function (item) {
        this.form = {
          name: item.name || '',
          slug: item.slug || '',
          category: item.category || '',
          description: item.description || '',
          price: String(item.price == null ? '' : item.price),
          image: item.image || '',
          available: !!item.available
        };
        this.editingId = item.id;
        this.errors = {};
        this.slugTouched = true;
        this.useImageUrl = !!(item.image && item.image.indexOf('http') === 0);
        this.modalOpen = true;
        this.focusModal();
      },
      focusModal: function () {
        var self = this;
        this.$nextTick(function () {
          var panel = self.$refs.modalPanel;
          var target = panel && panel.querySelector('[data-autofocus]');
          if (target) target.focus();
        });
      },
      close: function () { this.modalOpen = false; this.errors = {}; },
      validate: function () {
        var errors = {};
        if (!this.form.name.trim()) errors.name = 'Name is required.';
        if (!this.form.category.trim()) errors.category = 'Category is required.';
        var price = this.form.price;
        if (price === '' || price == null) errors.price = 'Price is required.';
        else if (isNaN(Number(price)) || Number(price) < 0) errors.price = 'Enter a valid price.';
        this.errors = errors;
        return Object.keys(errors).length === 0;
      },
      save: function () {
        var self = this;
        if (!this.validate()) return;
        this.saving = true;
        var payload = {
          name: this.form.name.trim(),
          slug: this.form.slug.trim(),
          category: this.form.category.trim(),
          description: this.form.description.trim(),
          price: Number(this.form.price),
          image: (this.form.image || '').trim(),
          available: !!this.form.available
        };
        var isEdit = !!this.editingId;
        var url = isEdit ? '/api/menu-items/' + this.editingId : '/api/menu-items';
        fetch(url, {
          method: isEdit ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrf },
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        })
          .then(function (res) { return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, data: data }; }); })
          .then(function (r) {
            if (!r.ok) throw new Error(r.data.detail || 'Saving failed.');
            self.sync(r.data.items);
            self.close();
            if (window.showToast) window.showToast(isEdit ? 'Menu item updated.' : 'Menu item added.', 'success');
          })
          .catch(function (error) { if (window.showToast) window.showToast(error.message, 'error'); })
          .finally(function () { self.saving = false; });
      },
      remove: function (item) {
        var self = this;
        if (!window.confirm('Delete "' + item.name + '" from the menu?')) return;
        fetch('/api/menu-items/' + item.id, {
          method: 'DELETE',
          headers: { 'X-CSRF-Token': this.csrf },
          credentials: 'same-origin'
        })
          .then(function (res) { return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, data: data }; }); })
          .then(function (r) {
            if (!r.ok) throw new Error(r.data.detail || 'Deleting failed.');
            self.sync(r.data.items);
            if (window.showToast) window.showToast('Menu item deleted.', 'success');
          })
          .catch(function (error) { if (window.showToast) window.showToast(error.message, 'error'); });
      },
      move: function (item, direction) {
        var self = this;
        fetch('/api/menu-items/' + item.id + '/move', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrf },
          credentials: 'same-origin',
          body: JSON.stringify({ direction: direction })
        })
          .then(function (res) { return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, data: data }; }); })
          .then(function (r) { if (!r.ok) throw new Error(r.data.detail || 'Reordering failed.'); self.sync(r.data.items); })
          .catch(function (error) { if (window.showToast) window.showToast(error.message, 'error'); });
      },
      sync: function (items) { if (Array.isArray(items)) this.items = items; },

      /* ---- photo ---- */
      pickFile: function () { var el = this.$refs.fileInput; if (el) el.click(); },
      onFileChosen: function (event) {
        var file = event.target.files && event.target.files[0];
        event.target.value = '';
        if (file) this.handleFile(file);
      },
      onDrop: function (event) {
        this.dragOver = false;
        var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
        if (file) this.handleFile(file);
      },
      handleFile: function (file) {
        var self = this;
        this.uploading = true;
        fileToJpegBlob(file)
          .then(function (blob) {
            if (!blob) throw new Error('That file could not be converted to an image.');
            var fd = new FormData();
            fd.append('file', blob, 'menu.jpg');
            return fetch('/api/uploads/menu-image', { method: 'POST', headers: { 'X-CSRF-Token': self.csrf }, credentials: 'same-origin', body: fd });
          })
          .then(function (res) { return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, data: data }; }); })
          .then(function (r) {
            if (!r.ok) throw new Error(r.data.detail || 'Upload failed.');
            self.form.image = r.data.url;
            self.useImageUrl = false;
          })
          .catch(function (error) { if (window.showToast) window.showToast(error.message, 'error'); })
          .finally(function () { self.uploading = false; });
      },
      removeImage: function () { this.form.image = ''; },

      /* ---- modal a11y: Esc + focus trap ---- */
      onModalKeydown: function (event) {
        if (event.key === 'Escape') { event.preventDefault(); this.close(); return; }
        if (event.key !== 'Tab') return;
        var modal = this.$refs.modalPanel;
        if (!modal) return;
        var focusables = modal.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])');
        if (!focusables.length) return;
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
  };
})();
