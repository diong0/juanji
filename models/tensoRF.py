from .tensorBase import *


class TensorVM(TensorBase):
    def __init__(self, aabb, gridSize, device, **kargs):
        super(TensorVM, self).__init__(aabb, gridSize, device, **kargs)

    def init_svd_volume(self, res, device):  #用于初始化奇异值分解（SVD）的体积相关参数，表示体积的分辨率，即体积的长、宽、高的像素数目，device表示计算设备
        self.plane_coef = torch.nn.Parameter(  # 平面系数张量
            0.1 * torch.randn((3, self.app_n_comp + self.density_n_comp, res, res), device=device))
        self.line_coef = torch.nn.Parameter(  # 线性系数张量
            0.1 * torch.randn((3, self.app_n_comp + self.density_n_comp, res, 1), device=device))
        self.basis_mat = torch.nn.Linear(self.app_n_comp * 3, self.app_dim, bias=False, device=device)  # 基础矩阵

    def get_optparam_groups(self, lr_init_spatialxyz=0.02, lr_init_network=0.001):
        # lr_init_spatialxyz是空间坐标系学习率的初始值，默认为 0.02 lr_init_network 是网络参数学习率的初始值，默认为 0.001。
        grad_vars = [{'params': self.line_coef, 'lr': lr_init_spatialxyz},
                     {'params': self.plane_coef, 'lr': lr_init_spatialxyz},
                     {'params': self.basis_mat.parameters(), 'lr': lr_init_network}]
        if isinstance(self.renderModule, torch.nn.Module):
            grad_vars += [{'params': self.renderModule.parameters(), 'lr': lr_init_network}]
        return grad_vars

    def compute_features(self, xyz_sampled):

        coordinate_plane = torch.stack((xyz_sampled[..., self.matMode[0]], xyz_sampled[..., self.matMode[1]],
                                        xyz_sampled[..., self.matMode[2]])).detach()
        coordinate_line = torch.stack(
            (xyz_sampled[..., self.vecMode[0]], xyz_sampled[..., self.vecMode[1]], xyz_sampled[..., self.vecMode[2]]))
        coordinate_line = torch.stack((torch.zeros_like(coordinate_line), coordinate_line), dim=-1).detach()

        plane_feats = F.grid_sample(self.plane_coef[:, -self.density_n_comp:], coordinate_plane,
                                    align_corners=True).view(
            -1, *xyz_sampled.shape[:1])
        line_feats = F.grid_sample(self.line_coef[:, -self.density_n_comp:], coordinate_line, align_corners=True).view(
            -1, *xyz_sampled.shape[:1])

        sigma_feature = torch.sum(plane_feats * line_feats, dim=0)

        plane_feats = F.grid_sample(self.plane_coef[:, :self.app_n_comp], coordinate_plane, align_corners=True).view(
            3 * self.app_n_comp, -1)
        line_feats = F.grid_sample(self.line_coef[:, :self.app_n_comp], coordinate_line, align_corners=True).view(
            3 * self.app_n_comp, -1)

        app_features = self.basis_mat((plane_feats * line_feats).T)

        return sigma_feature, app_features

    def compute_densityfeature(self, xyz_sampled):
        coordinate_plane = torch.stack((xyz_sampled[..., self.matMode[0]], xyz_sampled[..., self.matMode[1]],
                                        xyz_sampled[..., self.matMode[2]])).detach().view(3, -1, 1, 2)
        coordinate_line = torch.stack(
            (xyz_sampled[..., self.vecMode[0]], xyz_sampled[..., self.vecMode[1]], xyz_sampled[..., self.vecMode[2]]))
        coordinate_line = torch.stack((torch.zeros_like(coordinate_line), coordinate_line), dim=-1).detach().view(3, -1,
                                                                                                                  1, 2)

        plane_feats = F.grid_sample(self.plane_coef[:, -self.density_n_comp:], coordinate_plane,
                                    align_corners=True).view(
            -1, *xyz_sampled.shape[:1])
        line_feats = F.grid_sample(self.line_coef[:, -self.density_n_comp:], coordinate_line, align_corners=True).view(
            -1, *xyz_sampled.shape[:1])

        sigma_feature = torch.sum(plane_feats * line_feats, dim=0)

        return sigma_feature

    def compute_appfeature(self, xyz_sampled):
        coordinate_plane = torch.stack((xyz_sampled[..., self.matMode[0]], xyz_sampled[..., self.matMode[1]],
                                        xyz_sampled[..., self.matMode[2]])).detach().view(3, -1, 1, 2)
        coordinate_line = torch.stack(
            (xyz_sampled[..., self.vecMode[0]], xyz_sampled[..., self.vecMode[1]], xyz_sampled[..., self.vecMode[2]]))
        coordinate_line = torch.stack((torch.zeros_like(coordinate_line), coordinate_line), dim=-1).detach().view(3, -1,
                                                                                                                  1, 2)

        plane_feats = F.grid_sample(self.plane_coef[:, :self.app_n_comp], coordinate_plane, align_corners=True).view(
            3 * self.app_n_comp, -1)
        line_feats = F.grid_sample(self.line_coef[:, :self.app_n_comp], coordinate_line, align_corners=True).view(
            3 * self.app_n_comp, -1)

        app_features = self.basis_mat((plane_feats * line_feats).T)

        return app_features

    def vectorDiffs(self, vector_comps):
        total = 0

        for idx in range(len(vector_comps)):
            # print(self.line_coef.shape, vector_comps[idx].shape)
            n_comp, n_size = vector_comps[idx].shape[:-1]

            dotp = torch.matmul(vector_comps[idx].view(n_comp, n_size),
                                vector_comps[idx].view(n_comp, n_size).transpose(-1, -2))
            # print(vector_comps[idx].shape, vector_comps[idx].view(n_comp,n_size).transpose(-1,-2).shape, dotp.shape)
            non_diagonal = dotp.view(-1)[1:].view(n_comp - 1, n_comp + 1)[..., :-1]
            # print(vector_comps[idx].shape, vector_comps[idx].view(n_comp,n_size).transpose(-1,-2).shape, dotp.shape,non_diagonal.shape)
            total = total + torch.mean(torch.abs(non_diagonal))
        return total

    def vector_comp_diffs(self):

        return self.vectorDiffs(self.line_coef[:, -self.density_n_comp:]) + self.vectorDiffs(
            self.line_coef[:, :self.app_n_comp])

    @torch.no_grad()
    def up_sampling_VM(self, plane_coef, line_coef, res_target):

        for i in range(len(self.vecMode)):
            vec_id = self.vecMode[i]
            mat_id_0, mat_id_1 = self.matMode[i]

            plane_coef[i] = torch.nn.Parameter(
                F.interpolate(plane_coef[i].data, size=(res_target[mat_id_1], res_target[mat_id_0]), mode='bilinear',
                              align_corners=True))
            line_coef[i] = torch.nn.Parameter(
                F.interpolate(line_coef[i].data, size=(res_target[vec_id], 1), mode='bilinear', align_corners=True))

        # plane_coef[0] = torch.nn.Parameter(
        #     F.interpolate(plane_coef[0].data, size=(res_target[1], res_target[0]), mode='bilinear',
        #                   align_corners=True))
        # line_coef[0] = torch.nn.Parameter(
        #     F.interpolate(line_coef[0].data, size=(res_target[2], 1), mode='bilinear', align_corners=True))
        # plane_coef[1] = torch.nn.Parameter(
        #     F.interpolate(plane_coef[1].data, size=(res_target[2], res_target[0]), mode='bilinear',
        #                   align_corners=True))
        # line_coef[1] = torch.nn.Parameter(
        #     F.interpolate(line_coef[1].data, size=(res_target[1], 1), mode='bilinear', align_corners=True))
        # plane_coef[2] = torch.nn.Parameter(
        #     F.interpolate(plane_coef[2].data, size=(res_target[2], res_target[1]), mode='bilinear',
        #                   align_corners=True))
        # line_coef[2] = torch.nn.Parameter(
        #     F.interpolate(line_coef[2].data, size=(res_target[0], 1), mode='bilinear', align_corners=True))

        return plane_coef, line_coef

    @torch.no_grad()
    def upsample_volume_grid(self, res_target):
        # self.app_plane, self.app_line = self.up_sampling_VM(self.app_plane, self.app_line, res_target)
        # self.density_plane, self.density_line = self.up_sampling_VM(self.density_plane, self.density_line, res_target)

        scale = res_target[0] / self.line_coef.shape[2]  # assuming xyz have the same scale
        plane_coef = F.interpolate(self.plane_coef.detach().data, scale_factor=scale, mode='bilinear',
                                   align_corners=True)
        line_coef = F.interpolate(self.line_coef.detach().data, size=(res_target[0], 1), mode='bilinear',
                                  align_corners=True)
        self.plane_coef, self.line_coef = torch.nn.Parameter(plane_coef), torch.nn.Parameter(line_coef)
        self.compute_stepSize(res_target)
        print(f'upsamping to {res_target}')


class TensorVMSplit(TensorBase):
    def __init__(self, aabb, gridSize, device, **kargs):
        super(TensorVMSplit, self).__init__(aabb, gridSize, device, **kargs)

    def init_svd_volume(self, res, device):
        self.density_plane, self.density_line = self.init_one_svd(self.density_n_comp, self.gridSize, 0.1, device)
        self.app_plane, self.app_line = self.init_one_svd(self.app_n_comp, self.gridSize, 0.1, device)
        self.basis_mat = torch.nn.Linear(sum(self.app_n_comp), self.app_dim, bias=False).to(device)
        # linear全连接层,输入484848,输出27,[n,27]进mlp,得到颜色

        # 修改
        self.convolved_density_plane = None  # 添加新的属性来保存卷积后的结果

    def init_one_svd(self, n_component, gridSize, scale, device):
        plane_coef, line_coef = [], []
        for i in range(len(self.vecMode)):
            vec_id = self.vecMode[i]
            mat_id_0, mat_id_1 = self.matMode[i]
            plane_coef.append(torch.nn.Parameter(
                scale * torch.randn((1, n_component[i], gridSize[mat_id_1], gridSize[mat_id_0]))))  #
            line_coef.append(
                torch.nn.Parameter(scale * torch.randn((1, n_component[i], gridSize[vec_id], 1))))

        return torch.nn.ParameterList(plane_coef).to(device), torch.nn.ParameterList(line_coef).to(device)

    def get_optparam_groups(self, lr_init_spatialxyz=0.02, lr_init_network=0.001):
        grad_vars = [{'params': self.density_line, 'lr': lr_init_spatialxyz},
                     {'params': self.density_plane, 'lr': lr_init_spatialxyz},
                     {'params': self.app_line, 'lr': lr_init_spatialxyz},
                     {'params': self.app_plane, 'lr': lr_init_spatialxyz},
                     {'params': self.basis_mat.parameters(), 'lr': lr_init_network}]
        if isinstance(self.renderModule, torch.nn.Module):
            grad_vars += [{'params': self.renderModule.parameters(), 'lr': lr_init_network}]
        return grad_vars

    # 修改

    def extract_and_convolve_density_plane(self, kernel, device):
        
        # 提取 density_plane 的参数并进行卷积操作
        # :param kernel: 卷积核 (torch.Tensor)
        # :return: 卷积后的结果 (list of torch.Tensor)
        
        kernel_param = torch.randn((16, 16, 3, 3), device=device)
        kernel_line = torch.randn((16, 16, 3, 1), device=device)
        convolved_planes = []
        convolved_lines = []
        for param in self.density_plane:
            # param 的 shape 为 (1, n_component, height, width)
            # 进行卷积操作
            convolved_param = F.conv2d(param, kernel_param, padding=1)
            convolved_planes.append(torch.nn.Parameter(convolved_param))
        for L in self.density_line:
            # L 的 shape 为 (1, n_component, height, width)
            # 进行卷积擦操作
            convolved_line = F.conv2d(L, kernel_line, padding=1)
            convolved_lines.append(torch.nn.Parameter(convolved_line))
        return torch.nn.ParameterList(convolved_planes).to(device), torch.nn.ParameterList(convolved_lines).to(
            device)

    def vectorDiffs(self, vector_comps):
        total = 0

        for idx in range(len(vector_comps)):
            n_comp, n_size = vector_comps[idx].shape[1:-1]

            dotp = torch.matmul(vector_comps[idx].view(n_comp, n_size),
                                vector_comps[idx].view(n_comp, n_size).transpose(-1, -2))
            non_diagonal = dotp.view(-1)[1:].view(n_comp - 1, n_comp + 1)[..., :-1]
            total = total + torch.mean(torch.abs(non_diagonal))
        return total

    def vector_comp_diffs(self):
        return self.vectorDiffs(self.density_line) + self.vectorDiffs(self.app_line)

    def density_L1(self):
        total = 0
        for idx in range(len(self.density_plane)):
            total = total + torch.mean(torch.abs(self.density_plane[idx])) + torch.mean(torch.abs(self.density_line[
                                                                                                      idx]))  # + torch.mean(torch.abs(self.app_plane[idx])) + torch.mean(torch.abs(self.density_plane[idx]))
        return total

    def TV_loss_density(self, reg):
        total = 0
        for idx in range(len(self.density_plane)):
            total = total + reg(self.density_plane[idx]) * 1e-2  # + reg(self.density_line[idx]) * 1e-3
        return total

    def TV_loss_app(self, reg):
        total = 0
        for idx in range(len(self.app_plane)):
            total = total + reg(self.app_plane[idx]) * 1e-2  # + reg(self.app_line[idx]) * 1e-3
        return total

    # def get_density_plane_params(self):
    #     # 提取 density_plane 中的参数
    #     density_plane_params = []
    #     for param in self.density_plane:
    #         density_plane_params.append(param.detach().cpu().numpy())
    #     return density_plane_params

    def compute_densityfeature(self, xyz_sampled):

        # plane + line basis  matMode、vecMode用[0,1,2]表示vm分解中的平面和线
        coordinate_plane = torch.stack((
            xyz_sampled[..., self.matMode[0]],
            xyz_sampled[..., self.matMode[1]],
            xyz_sampled[..., self.matMode[2]]
        )).detach().view(3, -1, 1, 2)

        coordinate_line = torch.stack((
            xyz_sampled[..., self.vecMode[0]],
            xyz_sampled[..., self.vecMode[1]],
            xyz_sampled[..., self.vecMode[2]]))

        coordinate_line = torch.stack((
            torch.zeros_like(coordinate_line),
            coordinate_line)
            , dim=-1).detach().view(3, -1, 1, 2)

        sigma_feature = torch.zeros((xyz_sampled.shape[0],), device=xyz_sampled.device)
        # 创建sigma_feature,存储密度特征

        for idx_plane in range(len(self.density_plane)):
            # 修改,对体素网格进行卷积
            # density_plane_params = self.get_density_plane_params()

            # 在xy平面上的n个采样点，对某个点用其xy坐标通过二线性差值得到[1,16]的特征，n个采样点取得[n,16]特征
            plane_coef_point = F.grid_sample(
                self.density_plane[idx_plane],
                coordinate_plane[[idx_plane]],
                align_corners=True).view(-1, *xyz_sampled.shape[:1])  # 取平面的[n,16]特征

            line_coef_point = F.grid_sample(
                self.density_line[idx_plane],
                coordinate_line[[idx_plane]],
                align_corners=True).view(-1, *xyz_sampled.shape[:1])  # 取线的[n,16]特征

            sigma_feature = sigma_feature + torch.sum(plane_coef_point * line_coef_point, dim=0)
            # 对采样点在平面和线的[1,16]特征一一相乘得到[1,16]的列表，取每项总和为特征值，n个采样点便有n个特征值sigma_feature
        return sigma_feature

    def compute_appfeature(self, xyz_sampled):

        # plane + line basis
        coordinate_plane = torch.stack((
            xyz_sampled[..., self.matMode[0]],
            xyz_sampled[..., self.matMode[1]],
            xyz_sampled[..., self.matMode[2]]
        )).detach().view(3, -1, 1, 2)

        coordinate_line = torch.stack((
            xyz_sampled[..., self.vecMode[0]],
            xyz_sampled[..., self.vecMode[1]],
            xyz_sampled[..., self.vecMode[2]]))

        coordinate_line = torch.stack((
            torch.zeros_like(coordinate_line),
            coordinate_line),
            dim=-1).detach().view(3, -1, 1, 2)

        plane_coef_point, line_coef_point = [], []
        for idx_plane in range(len(self.app_plane)):
            plane_coef_point.append(F.grid_sample(
                self.app_plane[idx_plane],
                coordinate_plane[[idx_plane]],
                align_corners=True
            ).view(-1, *xyz_sampled.shape[:1]))

            line_coef_point.append(F.grid_sample(
                self.app_line[idx_plane],
                coordinate_line[[idx_plane]],
                align_corners=True
            ).view(-1, *xyz_sampled.shape[:1]))

        plane_coef_point, line_coef_point = torch.cat(plane_coef_point), torch.cat(line_coef_point)
        # 对于3种坐标表示(见论文),每个都取出[n,48]的特征并concat到一起,成为[n,3*48]
        return self.basis_mat((plane_coef_point * line_coef_point).T)  #进全连接层

    @torch.no_grad()
    def up_sampling_VM(self, plane_coef, line_coef, res_target):

        for i in range(len(self.vecMode)):
            vec_id = self.vecMode[i]
            mat_id_0, mat_id_1 = self.matMode[i]
            plane_coef[i] = torch.nn.Parameter(
                F.interpolate(plane_coef[i].data, size=(res_target[mat_id_1], res_target[mat_id_0]), mode='bilinear',
                              align_corners=True))
            line_coef[i] = torch.nn.Parameter(
                F.interpolate(line_coef[i].data, size=(res_target[vec_id], 1), mode='bilinear', align_corners=True))

        return plane_coef, line_coef

    @torch.no_grad()
    def upsample_volume_grid(self, res_target):
        self.app_plane, self.app_line = self.up_sampling_VM(self.app_plane, self.app_line, res_target)
        self.density_plane, self.density_line = self.up_sampling_VM(self.density_plane, self.density_line, res_target)

        self.update_stepSize(res_target)
        print(f'upsamping to {res_target}')

    @torch.no_grad()
    def shrink(self, new_aabb):
        print("====> shrinking ...")
        xyz_min, xyz_max = new_aabb
        t_l, b_r = (xyz_min - self.aabb[0]) / self.units, (xyz_max - self.aabb[0]) / self.units
        # print(new_aabb, self.aabb)
        # print(t_l, b_r,self.alphaMask.alpha_volume.shape)
        t_l, b_r = torch.round(torch.round(t_l)).long(), torch.round(b_r).long() + 1
        b_r = torch.stack([b_r, self.gridSize]).amin(0)

        for i in range(len(self.vecMode)):
            mode0 = self.vecMode[i]
            self.density_line[i] = torch.nn.Parameter(
                self.density_line[i].data[..., t_l[mode0]:b_r[mode0], :]
            )
            self.app_line[i] = torch.nn.Parameter(
                self.app_line[i].data[..., t_l[mode0]:b_r[mode0], :]
            )
            mode0, mode1 = self.matMode[i]
            self.density_plane[i] = torch.nn.Parameter(
                self.density_plane[i].data[..., t_l[mode1]:b_r[mode1], t_l[mode0]:b_r[mode0]]
            )
            self.app_plane[i] = torch.nn.Parameter(
                self.app_plane[i].data[..., t_l[mode1]:b_r[mode1], t_l[mode0]:b_r[mode0]]
            )

        if not torch.all(self.alphaMask.gridSize == self.gridSize):
            t_l_r, b_r_r = t_l / (self.gridSize - 1), (b_r - 1) / (self.gridSize - 1)
            correct_aabb = torch.zeros_like(new_aabb)
            correct_aabb[0] = (1 - t_l_r) * self.aabb[0] + t_l_r * self.aabb[1]
            correct_aabb[1] = (1 - b_r_r) * self.aabb[0] + b_r_r * self.aabb[1]
            print("aabb", new_aabb, "\ncorrect aabb", correct_aabb)
            new_aabb = correct_aabb

        newSize = b_r - t_l
        self.aabb = new_aabb
        self.update_stepSize((newSize[0], newSize[1], newSize[2]))


class TensorCP(TensorBase):
    def __init__(self, aabb, gridSize, device, **kargs):
        super(TensorCP, self).__init__(aabb, gridSize, device, **kargs)

    def init_svd_volume(self, res, device):
        self.density_line = self.init_one_svd(self.density_n_comp[0], self.gridSize, 0.2, device)
        self.app_line = self.init_one_svd(self.app_n_comp[0], self.gridSize, 0.2, device)
        self.basis_mat = torch.nn.Linear(self.app_n_comp[0], self.app_dim, bias=False).to(device)

    def init_one_svd(self, n_component, gridSize, scale, device):
        line_coef = []
        for i in range(len(self.vecMode)):
            vec_id = self.vecMode[i]
            line_coef.append(
                torch.nn.Parameter(scale * torch.randn((1, n_component, gridSize[vec_id], 1))))
        return torch.nn.ParameterList(line_coef).to(device)

    def get_optparam_groups(self, lr_init_spatialxyz=0.02, lr_init_network=0.001):
        grad_vars = [{'params': self.density_line, 'lr': lr_init_spatialxyz},
                     {'params': self.app_line, 'lr': lr_init_spatialxyz},
                     {'params': self.basis_mat.parameters(), 'lr': lr_init_network}]
        if isinstance(self.renderModule, torch.nn.Module):
            grad_vars += [{'params': self.renderModule.parameters(), 'lr': lr_init_network}]
        return grad_vars

    def compute_densityfeature(self, xyz_sampled):

        coordinate_line = torch.stack(
            (xyz_sampled[..., self.vecMode[0]], xyz_sampled[..., self.vecMode[1]], xyz_sampled[..., self.vecMode[2]]))
        coordinate_line = torch.stack((torch.zeros_like(coordinate_line), coordinate_line), dim=-1).detach().view(3, -1,
                                                                                                                  1, 2)

        line_coef_point = F.grid_sample(self.density_line[0], coordinate_line[[0]],
                                        align_corners=True).view(-1, *xyz_sampled.shape[:1])
        line_coef_point = line_coef_point * F.grid_sample(self.density_line[1], coordinate_line[[1]],
                                                          align_corners=True).view(-1, *xyz_sampled.shape[:1])
        line_coef_point = line_coef_point * F.grid_sample(self.density_line[2], coordinate_line[[2]],
                                                          align_corners=True).view(-1, *xyz_sampled.shape[:1])
        sigma_feature = torch.sum(line_coef_point, dim=0)

        return sigma_feature

    def compute_appfeature(self, xyz_sampled):

        coordinate_line = torch.stack(
            (xyz_sampled[..., self.vecMode[0]], xyz_sampled[..., self.vecMode[1]], xyz_sampled[..., self.vecMode[2]]))
        coordinate_line = torch.stack((torch.zeros_like(coordinate_line), coordinate_line), dim=-1).detach().view(3, -1,
                                                                                                                  1, 2)

        line_coef_point = F.grid_sample(self.app_line[0], coordinate_line[[0]],
                                        align_corners=True).view(-1, *xyz_sampled.shape[:1])
        line_coef_point = line_coef_point * F.grid_sample(self.app_line[1], coordinate_line[[1]],
                                                          align_corners=True).view(-1, *xyz_sampled.shape[:1])
        line_coef_point = line_coef_point * F.grid_sample(self.app_line[2], coordinate_line[[2]],
                                                          align_corners=True).view(-1, *xyz_sampled.shape[:1])

        return self.basis_mat(line_coef_point.T)

    @torch.no_grad()
    def up_sampling_Vector(self, density_line_coef, app_line_coef, res_target):

        for i in range(len(self.vecMode)):
            vec_id = self.vecMode[i]
            density_line_coef[i] = torch.nn.Parameter(
                F.interpolate(density_line_coef[i].data, size=(res_target[vec_id], 1), mode='bilinear',
                              align_corners=True))
            app_line_coef[i] = torch.nn.Parameter(
                F.interpolate(app_line_coef[i].data, size=(res_target[vec_id], 1), mode='bilinear', align_corners=True))

        return density_line_coef, app_line_coef

    @torch.no_grad()
    def upsample_volume_grid(self, res_target):
        self.density_line, self.app_line = self.up_sampling_Vector(self.density_line, self.app_line, res_target)

        self.update_stepSize(res_target)
        print(f'upsamping to {res_target}')

    @torch.no_grad()
    def shrink(self, new_aabb):
        print("====> shrinking ...")
        xyz_min, xyz_max = new_aabb
        t_l, b_r = (xyz_min - self.aabb[0]) / self.units, (xyz_max - self.aabb[0]) / self.units

        t_l, b_r = torch.round(torch.round(t_l)).long(), torch.round(b_r).long() + 1
        b_r = torch.stack([b_r, self.gridSize]).amin(0)

        for i in range(len(self.vecMode)):
            mode0 = self.vecMode[i]
            self.density_line[i] = torch.nn.Parameter(
                self.density_line[i].data[..., t_l[mode0]:b_r[mode0], :]
            )
            self.app_line[i] = torch.nn.Parameter(
                self.app_line[i].data[..., t_l[mode0]:b_r[mode0], :]
            )

        if not torch.all(self.alphaMask.gridSize == self.gridSize):
            t_l_r, b_r_r = t_l / (self.gridSize - 1), (b_r - 1) / (self.gridSize - 1)
            correct_aabb = torch.zeros_like(new_aabb)
            correct_aabb[0] = (1 - t_l_r) * self.aabb[0] + t_l_r * self.aabb[1]
            correct_aabb[1] = (1 - b_r_r) * self.aabb[0] + b_r_r * self.aabb[1]
            print("aabb", new_aabb, "\ncorrect aabb", correct_aabb)
            new_aabb = correct_aabb

        newSize = b_r - t_l
        self.aabb = new_aabb
        self.update_stepSize((newSize[0], newSize[1], newSize[2]))

    def density_L1(self):
        total = 0
        for idx in range(len(self.density_line)):
            total = total + torch.mean(torch.abs(self.density_line[idx]))
        return total

    def TV_loss_density(self, reg):
        total = 0
        for idx in range(len(self.density_line)):
            total = total + reg(self.density_line[idx]) * 1e-3
        return total

    def TV_loss_app(self, reg):
        total = 0
        for idx in range(len(self.app_line)):
            total = total + reg(self.app_line[idx]) * 1e-3
        return total
