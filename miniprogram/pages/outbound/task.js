const { createIdempotencyKey } = require('../../utils/idempotency');
const {
  buildOutboundConfirmation,
  buildScanBody,
} = require('../../utils/payload');
const { request, upload } = require('../../utils/request');
const {
  chooseNextSuffix,
  normalizeSuffix,
  parseQrPayload,
} = require('../../utils/scan');
const { requireSession } = require('../../utils/session');

Page({
  data: {
    session: null,
    taskId: '',
    orderId: '',
    task: null,
    order: null,
    scans: [],
    nextSuffix: '',
    busy: false,
    complete: false,
    can_confirm: false,
  },

  onLoad(options) {
    const session = requireSession();
    if (!session) return;
    this.setData({
      session,
      taskId: options.taskId,
      orderId: options.orderId,
    });
    this.loadTask();
  },

  async loadTask() {
    this.setData({ busy: true });
    try {
      const data = await request({
        path: `/shipyard/outbound/mobile/orders/${this.data.orderId}`,
      });
      const task = (data.tasks || []).find(
        (item) => item.task_id === this.data.taskId,
      );
      if (!task) throw new Error('出库任务不存在');
      const nextSuffix = chooseNextSuffix(
        task.expected_tag_suffixes,
        this.data.scans.map((item) => item.suffix),
      );
      const decoratedTask = {
        ...task,
        suffix_text: (task.expected_tag_suffixes || []).join('、'),
      };
      this.setData({
        task: decoratedTask,
        order: data,
        nextSuffix,
        complete: (data.tasks || []).every((item) => item.status === 'OUTBOUND'),
        scans: task.status === 'OUTBOUND' ? [] : this.data.scans,
      });
    } catch (error) {
      wx.showToast({ title: error.message, icon: 'none' });
    } finally {
      this.setData({ busy: false });
    }
  },

  async scanAndPhotograph() {
    const { task, busy } = this.data;
    if (!task || busy) return;
    if (task.status !== 'PENDING') {
      wx.showToast({ title: '该票已经完成出库', icon: 'none' });
      return;
    }
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
        suffix = await this.askSuffix(this.data.nextSuffix);
      }
      if (!suffix) return;
      if (!(task.expected_tag_suffixes || []).includes(suffix)) {
        throw new Error(`托盘 ${suffix} 不属于当前整票任务`);
      }
      if (this.data.scans.some((item) => item.suffix === suffix)) {
        throw new Error(`托盘 ${suffix} 已拍摄`);
      }

      const media = await wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['camera'],
        sizeType: ['compressed'],
      });
      const filePath = media.tempFiles[0].tempFilePath;
      const photo = await upload({
        path: `/shipyard/outbound/tasks/${task.task_id}/photos`,
        filePath,
        formData: { tag_suffix: suffix },
      });
      const scan = buildScanBody(task, suffix, raw, parsed);
      const validation = await request({
        path: `/shipyard/outbound/tasks/${task.task_id}/scan`,
        method: 'POST',
        data: scan,
      });
      const scans = [
        ...this.data.scans,
        {
          suffix,
          raw,
          scan,
          photo: photo.photo,
          validation,
        },
      ];
      const nextSuffix = chooseNextSuffix(
        task.expected_tag_suffixes,
        scans.map((item) => item.suffix),
      );
      this.setData({
        scans,
        nextSuffix,
        can_confirm: scans.length === task.expected_tag_suffixes.length,
      });
      wx.showToast({ title: `托盘 ${suffix} 核验通过`, icon: 'success' });
    } catch (error) {
      if (error.errMsg && error.errMsg.includes('cancel')) return;
      wx.showToast({ title: error.message || '扫码或拍照取消', icon: 'none' });
    } finally {
      this.setData({ busy: false });
    }
  },

  askSuffix(defaultSuffix) {
    return new Promise((resolve) => {
      wx.showModal({
        title: '确认托盘后缀',
        content: defaultSuffix ? `下一托应为 ${defaultSuffix}` : '',
        editable: true,
        placeholderText: defaultSuffix || '例如 1-1',
        success(result) {
          if (!result.confirm) {
            resolve('');
            return;
          }
          resolve(normalizeSuffix(result.content || defaultSuffix));
        },
        fail() {
          resolve('');
        },
      });
    });
  },

  removeScan(event) {
    const suffix = event.currentTarget.dataset.suffix;
    const scans = this.data.scans.filter((item) => item.suffix !== suffix);
    this.setData({
      scans,
      nextSuffix: chooseNextSuffix(
        this.data.task.expected_tag_suffixes,
        scans.map((item) => item.suffix),
      ),
      can_confirm: scans.length === this.data.task.expected_tag_suffixes.length,
    });
  },

  async confirmOutbound() {
    const { task, scans } = this.data;
    if (!task) return;
    const expected = task.expected_tag_suffixes || [];
    if (scans.length !== expected.length) {
      wx.showToast({
        title: `整票未齐套，还缺 ${expected.length - scans.length} 托`,
        icon: 'none',
      });
      return;
    }
    const body = buildOutboundConfirmation(
      createIdempotencyKey('outbound'),
      scans,
      `wx-${this.data.session.user.username}`,
    );
    this.setData({ busy: true });
    try {
      const result = await request({
        path: `/shipyard/outbound/tasks/${task.task_id}/confirm`,
        method: 'POST',
        data: body,
      });
      wx.showModal({
        title: '整票出库完成',
        content: `扣减 ${result.confirmation.quantity} 件\n区域 ${result.confirmation.location_path_snapshot}\n出库单状态 ${result.order.status}`,
        showCancel: false,
        success: () => wx.navigateBack(),
      });
    } catch (error) {
      wx.showToast({ title: error.message, icon: 'none' });
    } finally {
      this.setData({ busy: false });
    }
  },
});
