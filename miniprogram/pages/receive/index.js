const { createIdempotencyKey } = require('../../utils/idempotency');
const { buildReceiptConfirmation, buildScanBody } = require('../../utils/payload');
const { request, upload } = require('../../utils/request');
const {
  chooseNextSuffix,
  normalizeSuffix,
  parseQrPayload,
} = require('../../utils/scan');
const { requireSession } = require('../../utils/session');

const STATUS_LABELS = {
  PARSED: '待确认',
  CONFIRMED: '待收货',
  PARTIAL: '部分到货',
  CLOSED: '已到齐',
  PENDING: '待收货',
  RECEIVED: '已到货',
  EXPECTED: '待收货',
  IN_STOCK: '已入库',
  OUTBOUND: '已出库',
  EXCEPTION: '异常',
};

function statusClass(status) {
  if (['CLOSED', 'RECEIVED', 'IN_STOCK'].includes(status)) return 'chip-success';
  if (['PARTIAL', 'EXCEPTION'].includes(status)) return 'chip-warning';
  return '';
}

function numberText(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(3);
}

Page({
  data: {
    session: null,
    warehouseId: 1,
    manifests: [],
    selectedManifest: null,
    selectedManifestId: '',
    selectedTicket: null,
    scans: [],
    quantity: '',
    differenceReason: '',
    busy: false,
    loading: false,
    cameraVisible: false,
    pendingSuffix: '',
    nextSuffix: '',
  },

  onLoad() {
    const session = requireSession();
    if (!session) return;
    this.setData({
      session,
      warehouseId: session.warehouseId,
    });
    this.loadManifests();
  },

  onPullDownRefresh() {
    this.loadManifests().finally(() => wx.stopPullDownRefresh());
  },

  async loadManifests() {
    this.setData({ loading: true });
    try {
      const data = await request({
        path: `/shipyard/inbound/manifests?warehouse_id=${this.data.warehouseId}`,
      });
      const manifests = (data.manifests || []).map((item) => ({
        ...item,
        status_label: STATUS_LABELS[item.status] || item.status,
        status_class: statusClass(item.status),
      }));
      this.setData({ manifests });
      if (this.data.selectedManifest) {
        await this.openManifest(this.data.selectedManifest.manifest.manifest_id);
      }
    } catch (error) {
      wx.showToast({ title: error.message, icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },

  async openManifest(manifestId) {
    this.setData({ busy: true });
    try {
      const data = await request({
        path: `/shipyard/inbound/manifests/${manifestId}`,
      });
      const tickets = (data.tickets || []).map((ticket) => ({
        ...ticket,
        status_label: STATUS_LABELS[ticket.status] || ticket.status,
        status_class: statusClass(ticket.status),
        short_quantity_text: numberText(ticket.short_quantity),
        can_receive: ['EXPECTED', 'PARTIAL'].includes(ticket.status),
      }));
      const selectedManifest = { ...data, tickets };
      this.setData({
        selectedManifest,
        selectedManifestId: manifestId,
        selectedTicket: null,
        scans: [],
      });
    } catch (error) {
      wx.showToast({ title: error.message, icon: 'none' });
    } finally {
      this.setData({ busy: false });
    }
  },

  onManifestTap(event) {
    this.openManifest(event.currentTarget.dataset.id);
  },

  startTicket(event) {
    const ticketId = event.currentTarget.dataset.id;
    const ticket = this.data.selectedManifest.tickets.find(
      (item) => item.ticket_id === ticketId,
    );
    if (!ticket) return;
    if (!['EXPECTED', 'PARTIAL'].includes(ticket.status)) {
      wx.showToast({ title: '该票当前不能收货', icon: 'none' });
      return;
    }
    const remaining = Math.max(
      Number(ticket.declared_quantity) - Number(ticket.received_quantity),
      0,
    );
    this.setData({
      selectedTicket: ticket,
      scans: [],
      quantity: numberText(remaining),
      differenceReason: '',
    });
    wx.pageScrollTo({ selector: '#ticket-workbench', duration: 250 });
  },

  async scanAndPhotograph() {
    const ticket = this.data.selectedTicket;
    if (!ticket || this.data.busy) return;
    this.setData({ busy: true });
    try {
      const scanResult = await wx.scanCode({
        onlyFromCamera: true,
        scanType: ['qrCode', 'barCode'],
      });
      const raw = String(scanResult.result || '').trim();
      const parsed = parseQrPayload(raw);
      let suffix = normalizeSuffix(parsed.tag_suffix);
      if (!suffix) {
        suffix = await this.askSuffix();
      }
      if (!suffix) return;
      if (this.data.scans.some((item) => item.suffix === suffix)) {
        wx.showToast({ title: `托盘 ${suffix} 已拍摄`, icon: 'none' });
        return;
      }

      const media = await wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['camera'],
        sizeType: ['compressed'],
      });
      const filePath = media.tempFiles[0].tempFilePath;
      const photo = await upload({
        path: `/shipyard/inbound/tickets/${ticket.ticket_id}/photos`,
        filePath,
        formData: {
          photo_kind: 'PALLET',
          tag_suffix: suffix,
        },
      });
      const scanBody = buildScanBody(
        {
          ...ticket,
          planned_quantity: ticket.declared_quantity,
        },
        suffix,
        raw,
        parsed,
      );
      const validation = await request({
        path: `/shipyard/inbound/tickets/${ticket.ticket_id}/scan`,
        method: 'POST',
        data: scanBody,
      });
      const scans = [
        ...this.data.scans,
        {
          suffix,
          raw,
          parsed,
          scan: scanBody,
          photo: photo.photo,
          validation,
        },
      ];
      const expectedCount = Number(ticket.expected_pallet_count || 0);
      const nextSuffix = expectedCount > scans.length
        ? `下一托：${scans.length + 1}/${expectedCount}`
        : '';
      this.setData({ scans, nextSuffix });
      wx.showToast({ title: `托盘 ${suffix} 已核验`, icon: 'success' });
    } catch (error) {
      if (error.errMsg && error.errMsg.includes('cancel')) return;
      wx.showToast({ title: error.message || '扫码或拍照取消', icon: 'none' });
    } finally {
      this.setData({ busy: false });
    }
  },

  askSuffix() {
    return new Promise((resolve) => {
      wx.showModal({
        title: '填写托盘后缀',
        content: '',
        editable: true,
        placeholderText: '例如 1-1',
        success(result) {
          if (!result.confirm) {
            resolve('');
            return;
          }
          const suffix = normalizeSuffix(result.content);
          if (!suffix) {
            wx.showToast({ title: '后缀格式应为 1-1', icon: 'none' });
          }
          resolve(suffix);
        },
        fail() {
          resolve('');
        },
      });
    });
  },

  onQuantityInput(event) {
    this.setData({ quantity: event.detail.value });
  },

  onDifferenceReasonInput(event) {
    this.setData({ differenceReason: event.detail.value });
  },

  removeScan(event) {
    const suffix = event.currentTarget.dataset.suffix;
    const scans = this.data.scans.filter((item) => item.suffix !== suffix);
    this.setData({ scans });
  },

  async confirmReceipt() {
    const { selectedTicket, scans, quantity } = this.data;
    if (!selectedTicket || !scans.length) {
      wx.showToast({ title: '请先扫码并拍摄吊牌', icon: 'none' });
      return;
    }
    const expected = Number(selectedTicket.expected_pallet_count || 0);
    if (expected && scans.length < expected) {
      wx.showToast({ title: `托组未齐，还缺 ${expected - scans.length} 托`, icon: 'none' });
      return;
    }
    if (!Number(quantity) || Number(quantity) <= 0) {
      wx.showToast({ title: '请填写本次实收数量', icon: 'none' });
      return;
    }
    const differenceReason = this.data.differenceReason.trim();
    if (
      Number(quantity) < Number(selectedTicket.declared_quantity)
      && !differenceReason
    ) {
      wx.showToast({ title: '实收少于计划时必须填写差异原因', icon: 'none' });
      return;
    }
    const body = buildReceiptConfirmation({
      idempotencyKey: createIdempotencyKey('receipt'),
      quantity,
      evidence: scans,
      differenceReason,
      deviceId: `wx-${this.data.session.user.username}`,
    });
    this.setData({ busy: true });
    try {
      const result = await request({
        path: `/shipyard/inbound/tickets/${selectedTicket.ticket_id}/receipts`,
        method: 'POST',
        data: body,
      });
      wx.showModal({
        title: '收货已完成',
        content: `${result.ticket.item_name}\n实收 ${result.ticket.received_quantity} 件\n区域 ${result.receipt.location_path_snapshot}`,
        showCancel: false,
        success: () => {
          this.setData({ selectedTicket: null, scans: [] });
          this.loadManifests();
        },
      });
    } catch (error) {
      wx.showToast({ title: error.message, icon: 'none' });
    } finally {
      this.setData({ busy: false });
    }
  },
});
