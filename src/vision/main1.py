#!/usr/bin/env python
from __future__ import print_function

import argparse
import inspect
import os
import pickle
import random
import shutil
import sys
import time
from collections import OrderedDict
import traceback
from sklearn.metrics import confusion_matrix
import csv
import numpy as np
import glob

# torch
import torch
import torch.backends.cudnn as cudnn
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import yaml
from tensorboardX import SummaryWriter
from tqdm import tqdm

from src.vision.torchlight.torchlight import DictAction


def init_seed(seed):
    torch.cuda.manual_seed_all(seed)
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    # torch.backends.cudnn.enabled = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def import_class(import_str):
    mod_str, _sep, class_str = import_str.rpartition('.')
    __import__(mod_str)
    try:
        return getattr(sys.modules[mod_str], class_str)
    except AttributeError:
        raise ImportError('Class %s cannot be found (%s)' % (class_str, traceback.format_exception(*sys.exc_info())))


def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Unsupported value encountered.')


class LabelSmoothingCrossEntropy(nn.Module):
    def __init__(self, smoothing=0.1):
        super(LabelSmoothingCrossEntropy, self).__init__()
        self.smoothing = smoothing

    def forward(self, x, target):
        confidence = 1. - self.smoothing
        logprobs = F.log_softmax(x, dim=-1)
        nll_loss = -logprobs.gather(dim=-1, index=target.unsqueeze(1))
        nll_loss = nll_loss.squeeze(1)
        smooth_loss = -logprobs.mean(dim=-1)
        loss = confidence * nll_loss + self.smoothing * smooth_loss
        return loss.mean()


def get_parser():
    # parameter priority: command line > config > default
    parser = argparse.ArgumentParser(
        description='Spatial Temporal Graph Convolution Network')
    parser.add_argument(
        '--work-dir',
        default='./work_dir/temp',
        help='the work folder for storing results')

    parser.add_argument('-model_saved_name', default='')
    parser.add_argument(
        '--config',
        default='./config/nturgbd-cross-view/test_bone.yaml',
        help='path to the configuration file')

    # processor
    parser.add_argument(
        '--phase', default='train', help='must be train or test')
    parser.add_argument(
        '--save-score',
        type=str2bool,
        default=False,
        help='if ture, the classification score will be stored')

    # visulize and debug
    parser.add_argument(
        '--seed', type=int, default=1, help='random seed for pytorch')
    parser.add_argument(
        '--log-interval',
        type=int,
        default=100,
        help='the interval for printing messages (#iteration)')
    parser.add_argument(
        '--save-interval',
        type=int,
        default=1,
        help='the interval for storing models (#iteration)')
    parser.add_argument(
        '--save-epoch',
        type=int,
        default=30,
        help='the start epoch to save model (#iteration)')
    parser.add_argument(
        '--eval-interval',
        type=int,
        default=5,
        help='the interval for evaluating models (#iteration)')
    parser.add_argument(
        '--print-log',
        type=str2bool,
        default=True,
        help='print logging or not')
    parser.add_argument(
        '--show-topk',
        type=int,
        default=[1, 5],
        nargs='+',
        help='which Top K accuracy will be shown')

    # feeder
    parser.add_argument(
        '--feeder', default='feeder.feeder', help='data loader will be used')
    parser.add_argument(
        '--num-worker',
        type=int,
        default=32,
        help='the number of worker for data loader')
    parser.add_argument(
        '--train-feeder-args',
        action=DictAction,
        default=dict(),
        help='the arguments of data loader for training')

    # 🔥 THÊM Tham số cho tập Validation
    parser.add_argument(
        '--val-feeder-args',
        action=DictAction,
        default=dict(),
        help='the arguments of data loader for validation')

    parser.add_argument(
        '--test-feeder-args',
        action=DictAction,
        default=dict(),
        help='the arguments of data loader for test')

    # model
    parser.add_argument('--model', default=None, help='the model will be used')
    parser.add_argument(
        '--model-args',
        action=DictAction,
        default=dict(),
        help='the arguments of model')
    parser.add_argument(
        '--weights',
        default=None,
        help='the weights for network initialization')
    parser.add_argument(
        '--ignore-weights',
        type=str,
        default=[],
        nargs='+',
        help='the name of weights which will be ignored in the initialization')

    # optim
    parser.add_argument(
        '--base-lr', type=float, default=0.01, help='initial learning rate')
    parser.add_argument(
        '--step',
        type=int,
        default=[20, 40, 60],
        nargs='+',
        help='the epoch where optimizer reduce the learning rate')
    parser.add_argument(
        '--device',
        type=int,
        default=0,
        nargs='+',
        help='the indexes of GPUs for training or testing')
    parser.add_argument('--optimizer', default='SGD', help='type of optimizer')
    parser.add_argument(
        '--nesterov', type=str2bool, default=False, help='use nesterov or not')
    parser.add_argument(
        '--batch-size', type=int, default=256, help='training batch size')
    parser.add_argument(
        '--test-batch-size', type=int, default=256, help='test batch size')
    parser.add_argument(
        '--start-epoch',
        type=int,
        default=0,
        help='start training from which epoch')
    parser.add_argument(
        '--num-epoch',
        type=int,
        default=80,
        help='stop training in which epoch')
    parser.add_argument(
        '--weight-decay',
        type=float,
        default=0.0005,
        help='weight decay for optimizer')
    parser.add_argument(
        '--lr-ratio',
        type=float,
        default=0.001,
        help='decay rate for learning rate')
    parser.add_argument(
        '--lr-decay-rate',
        type=float,
        default=0.1,
        help='decay rate for learning rate')
    parser.add_argument('--warm_up_epoch', type=int, default=0)
    parser.add_argument('--loss-type', type=str, default='CE')

    return parser


class Processor():
    """
        Processor for Skeleton-based Action Recgnition
    """

    def __init__(self, arg):
        self.arg = arg
        self.save_arg()
        if arg.phase == 'train':
            if not arg.train_feeder_args['debug']:
                arg.model_saved_name = os.path.join(arg.work_dir, 'runs')
                if os.path.isdir(arg.model_saved_name):
                    print('log_dir: ', arg.model_saved_name, 'already exist')
                    answer = input('delete it? y/n:')
                    if answer == 'y':
                        shutil.rmtree(arg.model_saved_name)
                        print('Dir removed: ', arg.model_saved_name)
                        input('Refresh the website of tensorboard by pressing any keys')
                    else:
                        print('Dir not removed: ', arg.model_saved_name)
                self.train_writer = SummaryWriter(os.path.join(arg.model_saved_name, 'train'), 'train')
                self.val_writer = SummaryWriter(os.path.join(arg.model_saved_name, 'val'), 'val')
            else:
                self.train_writer = self.val_writer = SummaryWriter(os.path.join(arg.model_saved_name, 'test'), 'test')
        self.global_step = 0
        self.load_model()

        if self.arg.phase == 'model_size':
            pass
        else:
            self.load_optimizer()
            self.load_data()
        self.lr = self.arg.base_lr
        self.best_acc = 0
        self.best_acc_epoch = 0

        self.model = self.model.cuda(self.output_device)

        if type(self.arg.device) is list:
            if len(self.arg.device) > 1:
                self.model = nn.DataParallel(
                    self.model,
                    device_ids=self.arg.device,
                    output_device=self.output_device)

    def load_data(self):
        Feeder = import_class(self.arg.feeder)
        self.data_loader = dict()
        if self.arg.phase == 'train':
            self.data_loader['train'] = torch.utils.data.DataLoader(
                dataset=Feeder(**self.arg.train_feeder_args),
                batch_size=self.arg.batch_size,
                shuffle=True,
                num_workers=self.arg.num_worker,
                drop_last=True,
                worker_init_fn=init_seed)

            # 🔥 LOAD TẬP VALIDATION
            if getattr(self.arg, 'val_feeder_args', None):
                self.data_loader['val'] = torch.utils.data.DataLoader(
                    dataset=Feeder(**self.arg.val_feeder_args),
                    batch_size=self.arg.test_batch_size,
                    shuffle=False,
                    num_workers=self.arg.num_worker,
                    drop_last=False,
                    worker_init_fn=init_seed)

        self.data_loader['test'] = torch.utils.data.DataLoader(
            dataset=Feeder(**self.arg.test_feeder_args),
            batch_size=self.arg.test_batch_size,
            shuffle=False,
            num_workers=self.arg.num_worker,
            drop_last=False,
            worker_init_fn=init_seed)

    def load_model(self):
        output_device = self.arg.device[0] if type(self.arg.device) is list else self.arg.device
        self.output_device = output_device
        Model = import_class(self.arg.model)
        shutil.copy2(inspect.getfile(Model), self.arg.work_dir)
        print(Model)
        self.model = Model(**self.arg.model_args)
        if self.arg.loss_type == 'CE':
            self.loss = nn.CrossEntropyLoss().cuda(output_device)
        else:
            self.loss = LabelSmoothingCrossEntropy(smoothing=0.1).cuda(output_device)

        if self.arg.weights:
            try:
                self.global_step = int(self.arg.weights[:-3].split('-')[-1])
            except:
                self.global_step = 0
            self.print_log('Load weights from {}.'.format(self.arg.weights))
            self.print_log('Load weights from {}.'.format(self.arg.weights))
            if '.pkl' in self.arg.weights:
                with open(self.arg.weights, 'r') as f:
                    weights = pickle.load(f)
            else:
                weights = torch.load(self.arg.weights)

            weights = OrderedDict([[k.split('module.')[-1], v.cuda(output_device)] for k, v in weights.items()])

            keys = list(weights.keys())
            for w in self.arg.ignore_weights:
                for key in keys:
                    if w in key:
                        if weights.pop(key, None) is not None:
                            self.print_log('Sucessfully Remove Weights: {}.'.format(key))
                        else:
                            self.print_log('Can Not Remove Weights: {}.'.format(key))

            try:
                self.model.load_state_dict(weights)
            except:
                state = self.model.state_dict()
                diff = list(set(state.keys()).difference(set(weights.keys())))
                print('Can not find these weights:')
                for d in diff:
                    print('  ' + d)
                state.update(weights)
                self.model.load_state_dict(state)

    def load_optimizer(self):
        if self.arg.optimizer == 'SGD':
            self.optimizer = optim.SGD(
                self.model.parameters(),
                lr=self.arg.base_lr,
                momentum=0.9,
                nesterov=self.arg.nesterov,
                weight_decay=self.arg.weight_decay)
        elif self.arg.optimizer == 'Adam':
            self.optimizer = optim.Adam(
                self.model.parameters(),
                lr=self.arg.base_lr,
                weight_decay=self.arg.weight_decay)
        else:
            raise ValueError()

        self.print_log('using warm up, epoch: {}'.format(self.arg.warm_up_epoch))

    def save_arg(self):
        arg_dict = vars(self.arg)
        if not os.path.exists(self.arg.work_dir):
            os.makedirs(self.arg.work_dir)
        with open('{}/config.yaml'.format(self.arg.work_dir), 'w') as f:
            f.write(f"# command line: {' '.join(sys.argv)}\n\n")
            yaml.dump(arg_dict, f)

    def adjust_learning_rate(self, epoch, idx):
        if self.arg.optimizer == 'SGD' or self.arg.optimizer == 'Adam':
            if epoch < self.arg.warm_up_epoch:
                lr = self.arg.base_lr * (epoch + 1) / self.arg.warm_up_epoch
            else:
                T_max = len(self.data_loader['train']) * (self.arg.num_epoch - self.arg.warm_up_epoch)
                T_cur = len(self.data_loader['train']) * (epoch - self.arg.warm_up_epoch) + idx

                eta_min = self.arg.base_lr * self.arg.lr_ratio
                lr = eta_min + 0.5 * (self.arg.base_lr - eta_min) * (1 + np.cos((T_cur / T_max) * np.pi))
            for param_group in self.optimizer.param_groups:
                param_group['lr'] = lr
            return lr
        else:
            raise ValueError()

    def print_time(self):
        localtime = time.asctime(time.localtime(time.time()))
        self.print_log("Local current time :  " + localtime)

    def print_log(self, str, print_time=True):
        if print_time:
            localtime = time.asctime(time.localtime(time.time()))
            str = "[ " + localtime + ' ] ' + str
        print(str)
        if self.arg.print_log:
            # Thêm encoding='utf-8' để đọc/ghi tiếng Việt có dấu thoải mái trên Windows
            with open('{}/log.txt'.format(self.arg.work_dir), 'a', encoding='utf-8') as f:
                print(str, file=f)

    def record_time(self):
        self.cur_time = time.time()
        return self.cur_time

    def split_time(self):
        split_time = time.time() - self.cur_time
        self.record_time()
        return split_time

    def train(self, epoch, save_model=False):
        self.model.train()
        self.print_log('----------------------------------------------------')
        self.print_log('Training epoch: {}'.format(epoch + 1))

        # 🔥 ĐO THỜI GIAN BẮT ĐẦU EPOCH
        epoch_start_time = time.time()

        loader = self.data_loader['train']
        loss_value = []
        acc_top1_value = []
        acc_top5_value = []

        self.train_writer.add_scalar('epoch', epoch, self.global_step)
        self.record_time()
        timer = dict(dataloader=0.001, model=0.001, statistics=0.001)
        process = tqdm(loader, desc='Train')

        # 🚀 FIX: Feeder cũ chỉ trả về (data, label, index)
        for batch_idx, (data, label, index) in enumerate(process):
            self.adjust_learning_rate(epoch, batch_idx)
            self.global_step += 1
            with torch.no_grad():
                data = data.float().cuda(self.output_device)
                label = label.long().cuda(self.output_device)
            timer['dataloader'] += self.split_time()

            # forward
            # 🚀 FIX: Model cũ chỉ nhận `data`
            output = self.model(data)
            loss = self.loss(output, label)

            # backward
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

            loss_value.append(loss.data.item())
            timer['model'] += self.split_time()

            # 🔥 TÍNH TOP-1 VÀ TOP-5 NGAY TRONG LÚC TRAIN
            with torch.no_grad():
                num_classes = output.size(1)
                k_val = min(5, num_classes)  # Tự động chọn k = 2 nếu chỉ có 2 class, hoặc k = 5 nếu đủ lớp
                
                _, predict_label = torch.topk(output.data, k_val, dim=1)
                true_label = label.data.view(-1, 1).expand_as(predict_label)
                correct = predict_label == true_label

                acc_top1 = correct[:, 0].float().mean()
                acc_top5 = correct[:, :k_val].float().sum(dim=1).mean()

                acc_top1_value.append(acc_top1.item())
                acc_top5_value.append(acc_top5.item())

            self.train_writer.add_scalar('acc_top1', acc_top1.item(), self.global_step)
            self.train_writer.add_scalar('loss', loss.data.item(), self.global_step)

            # statistics
            self.lr = self.optimizer.param_groups[0]['lr']
            self.train_writer.add_scalar('lr', self.lr, self.global_step)
            timer['statistics'] += self.split_time()

        # 🔥 TÍNH THỜI GIAN KẾT THÚC EPOCH
        epoch_time = time.time() - epoch_start_time

        proportion = {
            k: '{:02d}%'.format(int(round(v * 100 / sum(timer.values()))))
            for k, v in timer.items()
        }

        self.print_log('\tMean training loss: {:.4f}.'.format(np.mean(loss_value)))
        self.print_log('\tMean training acc (Top-1): {:.2f}%.'.format(np.mean(acc_top1_value) * 100))
        self.print_log('\tMean training acc (Top-5): {:.2f}%.'.format(np.mean(acc_top5_value) * 100))
        self.print_log('\tTime consumption: [Data]{dataloader}, [Network]{model}'.format(**proportion))
        self.print_log('\tEpoch Total Time: {:.2f} seconds.'.format(epoch_time))

    def eval(self, epoch, save_score=False, loader_name=['test'], wrong_file=None, result_file=None):
        if wrong_file is not None:
            f_w = open(wrong_file, 'w')
        if result_file is not None:
            f_r = open(result_file, 'w')

        self.model.eval()
        self.print_log('Eval epoch: {}'.format(epoch + 1))

        final_accuracy = 0.0
        each_acc = None
        confusion = None

        for ln in loader_name:
            loss_value = []
            score_frag = []
            label_list = []
            pred_list = []
            step = 0
            process = tqdm(self.data_loader[ln], desc=f'Eval ({ln})')

            # 🚀 FIX: Tương tự như hàm Train
            for batch_idx, (data, label, index) in enumerate(process):
                label_list.append(label)
                with torch.no_grad():
                    data = data.float().cuda(self.output_device)
                    label = label.long().cuda(self.output_device)

                    # 🚀 FIX: Model cũ chỉ nhận `data`
                    output = self.model(data)

                    loss = self.loss(output, label)

                    score_frag.append(output.data.cpu().numpy())
                    loss_value.append(loss.data.item())

                    _, predict_label = torch.max(output.data, 1)
                    pred_list.append(predict_label.data.cpu().numpy())
                    step += 1

                if wrong_file is not None or result_file is not None:
                    predict = list(predict_label.cpu().numpy())
                    true = list(label.data.cpu().numpy())
                    for i, x in enumerate(predict):
                        if result_file is not None:
                            f_r.write(str(x) + ',' + str(true[i]) + '\n')
                        if x != true[i] and wrong_file is not None:
                            f_w.write(str(index[i]) + ',' + str(x) + ',' + str(true[i]) + '\n')

            score = np.concatenate(score_frag)
            loss = np.mean(loss_value)

            if 'ucla' in self.arg.feeder:
                self.data_loader[ln].dataset.sample_name = np.arange(len(score))

            accuracy = self.data_loader[ln].dataset.top_k(score, 1)
            final_accuracy = accuracy  # Gán để trả về cho hàm start()

            # Chỉ cập nhật best model dựa trên tập validation (hoặc test nếu không có val)
            if ln == ('val' if 'val' in self.data_loader else 'test'):
                pass

            self.print_log('\tAccuracy: {:.2f}%'.format(accuracy * 100))

            if self.arg.phase == 'train' and ln == 'val':
                self.val_writer.add_scalar('loss', loss, self.global_step)
                self.val_writer.add_scalar('acc', accuracy, self.global_step)

            score_dict = dict(zip(self.data_loader[ln].dataset.sample_name, score))
            self.print_log('\tMean {} loss of {} batches: {:.4f}.'.format(
                ln, len(self.data_loader[ln]), np.mean(loss_value)))

            for k in self.arg.show_topk:
                self.print_log('\tTop{}: {:.2f}%'.format(
                    k, 100 * self.data_loader[ln].dataset.top_k(score, k)))

            if save_score:
                with open('{}/epoch{}_{}_score.pkl'.format(
                        self.arg.work_dir, epoch + 1, ln), 'wb') as f:
                    pickle.dump(score_dict, f)

            # 🔥 TÍNH TOÁN MA TRẬN NHẦM LẪN Ở ĐÂY ĐỂ TRẢ VỀ HÀM START
            label_list = np.concatenate(label_list)
            pred_list = np.concatenate(pred_list)
            confusion = confusion_matrix(label_list, pred_list)
            list_diag = np.diag(confusion)
            list_raw_sum = np.sum(confusion, axis=1)
            # Tránh lỗi chia cho 0
            list_raw_sum[list_raw_sum == 0] = 1
            each_acc = list_diag / list_raw_sum

            # Chỉ lưu CSV ngay tại đây nếu chạy lệnh test độc lập (--phase test)
            if save_score:
                with open('{}/epoch{}_{}_each_class_acc.csv'.format(self.arg.work_dir, epoch + 1, ln), 'w') as f:
                    writer = csv.writer(f)
                    writer.writerow(each_acc)
                    writer.writerows(confusion)

        # 🚀 FIX: Trả về cả 3 tham số để hàm start lưu vào Top 5
        return final_accuracy, each_acc, confusion

    def start(self):
        if self.arg.phase == 'train':
            self.print_log('Parameters:\n{}\n'.format(str(vars(self.arg))))
            self.global_step = self.arg.start_epoch * len(self.data_loader['train']) / self.arg.batch_size

            def count_parameters(model):
                return sum(p.numel() for p in model.parameters() if p.requires_grad)

            self.print_log(f'# Parameters: {count_parameters(self.model)}')

            # 🔥 KHỞI TẠO DANH SÁCH LƯU TOP 5 EPOCH
            self.top5_models = []

            for epoch in range(self.arg.start_epoch, self.arg.num_epoch):
                # 1. Chạy quá trình Training
                self.train(epoch, save_model=False)

                # 2. Chạy quá trình Validation (Nếu có cấu hình)
                eval_loader = ['val'] if 'val' in self.data_loader else ['test']
                
                # 🚀 FIX: Nhận đủ 3 giá trị từ hàm eval mới
                current_acc, each_acc, confusion = self.eval(epoch, save_score=False, loader_name=eval_loader)

                # 3. 🔥 LƯU BEST MODEL (Tuyệt đối nhất)
                if current_acc > self.best_acc:
                    self.best_acc = current_acc
                    self.best_acc_epoch = epoch + 1
                    self.print_log(f'\t=> New best model found at epoch {self.best_acc_epoch} with Acc: {self.best_acc * 100:.2f}%!')
                    state_dict = self.model.state_dict()
                    weights = OrderedDict([[k.split('module.')[-1], v.cpu()] for k, v in state_dict.items()])
                    torch.save(weights, self.arg.model_saved_name + '-best_val.pt')

                # =======================================================
                # 4. 🔥 CƠ CHẾ BẢNG XẾP HẠNG: QUẢN LÝ TOP 5 MODEL (Lưu cả .pt và .csv)
                # =======================================================
                # Thêm epoch hiện tại vào danh sách
                self.top5_models.append({
                    'acc': current_acc, 
                    'epoch': epoch + 1,
                    'each_acc': each_acc,
                    'confusion': confusion
                })
                # Sắp xếp danh sách giảm dần theo điểm Accuracy
                self.top5_models = sorted(self.top5_models, key=lambda x: x['acc'], reverse=True)

                # Kiểm tra nếu epoch vừa chạy nằm trong Top 5
                if any(m['epoch'] == (epoch + 1) for m in self.top5_models[:5]):
                    # Lưu file .pt
                    state_dict = self.model.state_dict()
                    weights = OrderedDict([[k.split('module.')[-1], v.cpu()] for k, v in state_dict.items()])
                    pt_path = self.arg.model_saved_name + f"-top_epoch{epoch + 1}_acc_{current_acc*100:.2f}.pt"
                    torch.save(weights, pt_path)
                    
                    # Lưu file .csv
                    csv_path = self.arg.model_saved_name + f"-top_epoch{epoch + 1}_acc_{current_acc*100:.2f}_matrix.csv"
                    with open(csv_path, 'w') as f:
                        writer = csv.writer(f)
                        writer.writerow(each_acc)
                        writer.writerows(confusion)
                    
                    self.print_log(f'\t=> Epoch {epoch + 1} lọt vào Top 5, đã lưu tệp .pt và .csv!')

                # Nếu bảng xếp hạng phình to hơn 5, "trảm" thằng bét bảng
                if len(self.top5_models) > 5:
                    worst_model = self.top5_models.pop(-1) # Rút thằng bét ra khỏi list
                    
                    # Tìm file vật lý trên ổ cứng và xóa sạch
                    old_pt = self.arg.model_saved_name + f"-top_epoch{worst_model['epoch']}_acc_{worst_model['acc']*100:.2f}.pt"
                    old_csv = self.arg.model_saved_name + f"-top_epoch{worst_model['epoch']}_acc_{worst_model['acc']*100:.2f}_matrix.csv"
                    
                    if os.path.exists(old_pt):
                        os.remove(old_pt)
                    if os.path.exists(old_csv):
                        os.remove(old_csv)
                        
            # 🚀 FIX LỖI SPAM: KÉO KHỐI TỔNG KẾT NÀY RA HẲN NGOÀI VÒNG LẶP FOR
            self.print_log('\n=========================================')
            self.print_log('Training Complete!')
            self.print_log('=========================================')

            num_params = sum(p.numel() for p in self.model.parameters() if p.requires_grad)

            self.print_log(f'Best Validation Accuracy: {self.best_acc * 100:.2f}%')
            self.print_log(f'Achieved at Epoch: {self.best_acc_epoch}')
            self.print_log(f'Model name: {self.arg.work_dir}')
            self.print_log(f'Model total number of params: {num_params}')

        elif self.arg.phase == 'test':
            if self.arg.weights is None:
                weight_paths = glob.glob(os.path.join(self.arg.work_dir, '*top_epoch*.pt'))
                if len(weight_paths) == 0:
                    raise ValueError(f'Không tìm thấy file *top_epoch*.pt nào trong {self.arg.work_dir}.')
            else:
                weight_paths = [self.arg.weights] 

            self.print_log('\n🚀 ĐANG QUÉT NGẦM TÌM MODEL MẠNH NHẤT TRÊN TẬP TEST (Vui lòng đợi)...')
            
            best_test_acc = 0.0
            best_w_path = None
            best_fake_epoch = 0
            original_print_log = self.arg.print_log
            self.arg.print_log = False
            
            # 1. VÒNG SƠ KHẢO: Cho 5 model thi đấu âm thầm
            for w_path in weight_paths:
                weights = torch.load(w_path)
                weights = OrderedDict([[k.split('module.')[-1], v.cuda(self.output_device)] for k, v in weights.items()])
                try:
                    self.model.load_state_dict(weights)
                except Exception:
                    continue

                try:
                    ep_str = w_path.split('epoch')[1].split('_')[0]
                    fake_epoch = int(ep_str) - 1 
                except:
                    fake_epoch = 9999 
                test_acc, _, _ = self.eval(epoch=fake_epoch, save_score=False, loader_name=['test'])
                
                # Cập nhật bảng xếp hạng
                if test_acc > best_test_acc:
                    best_test_acc = test_acc
                    best_w_path = w_path
                    best_fake_epoch = fake_epoch

            self.arg.print_log = original_print_log # Bật lại log
            self.arg.save_score = True              # Bật công tắc xuất file Score
            
            self.print_log('\n' + '='*55)
            self.print_log('👑 ĐÃ TÌM THẤY VUA TRÊN TẬP TEST: {}'.format(os.path.basename(best_w_path)))
            self.print_log('Tiến hành trích xuất file Score (.pkl) và Matrix (.csv)...')
            self.print_log('='*55)
            weights = torch.load(best_w_path)
            weights = OrderedDict([[k.split('module.')[-1], v.cuda(self.output_device)] for k, v in weights.items()])
            self.model.load_state_dict(weights)
            
            wf = best_w_path.replace('.pt', '_wrong.txt')
            rf = best_w_path.replace('.pt', '_right.txt')
            self.eval(epoch=best_fake_epoch, save_score=True, loader_name=['test'], wrong_file=wf, result_file=rf)
            
            self.print_log('\n HOÀN THÀNH!\n')
if __name__ == '__main__':
    parser = get_parser()

    # load arg form config file
    p = parser.parse_args()
    if p.config is not None:
        with open(p.config, 'r', encoding='utf-8') as f:
            default_arg = yaml.safe_load(f)  # Thay đổi sang safe_load để an toàn hơn
        key = vars(p).keys()
        for k in default_arg.keys():
            if k not in key:
                print('WRONG ARG: {}'.format(k))
                assert (k in key)
        parser.set_defaults(**default_arg)

    arg = parser.parse_args()
    init_seed(arg.seed)
    processor = Processor(arg)
    processor.start()