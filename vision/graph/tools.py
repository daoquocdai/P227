import numpy as np

def edge2mat(link, num_node):
    A = np.zeros((num_node, num_node))
    for i, j in link:
        A[j, i] = 1
    return A

def normalize_digraph(A):
    Dl = np.sum(A, 0)
    h, w = A.shape
    Dn = np.zeros((w, w))
    for i in range(w):
        if Dl[i] > 0:
            Dn[i, i] = Dl[i] ** (-1)
    AD = np.dot(A, Dn)
    return AD

def get_spatial_graph(num_node, hierarchy):
    A = []
    for i in range(len(hierarchy)):
        A.append(normalize_digraph(edge2mat(hierarchy[i], num_node)))
    A = np.stack(A)
    return A

def get_spatial_graph_original(num_node, self_link, inward, outward):
    I = edge2mat(self_link, num_node)
    In = normalize_digraph(edge2mat(inward, num_node))
    Out = normalize_digraph(edge2mat(outward, num_node))
    A = np.stack((I, In, Out))
    return A

def normalize_adjacency_matrix(A):
    node_degrees = A.sum(-1)
    degs_inv_sqrt = np.power(node_degrees, -0.5)
    norm_degs_matrix = np.eye(len(node_degrees)) * degs_inv_sqrt
    return (norm_degs_matrix @ A @ norm_degs_matrix).astype(np.float32)

def get_graph(num_node, edges):
    I = edge2mat(edges[0], num_node)
    Forward = normalize_digraph(edge2mat(edges[1], num_node))
    Reverse = normalize_digraph(edge2mat(edges[2], num_node))
    A = np.stack((I, Forward, Reverse))
    return A # 3, 25, 25

def get_hierarchical_graph(num_node, edges):
    A = []
    for edge in edges:
        A.append(get_graph(num_node, edge))
    A = np.stack(A)
    return A

def get_groups(dataset='NTU', CoM=20):
    groups = []

    if dataset == 'NTU':
        # Center of Mass: 1 (Middle of Spine - Index cũ là 2)
        if CoM == 1:
            groups.append([1])
            groups.append([0, 20])
            groups.append([12, 16, 2, 4, 8])
            groups.append([13, 17, 3, 5, 9])
            groups.append([14, 18, 6, 10])
            groups.append([15, 19, 7, 11])
            groups.append([21, 22, 23, 24])

        # Center of mass: 20 (Spine / Center of Shoulders - Index cũ là 21)
        elif CoM == 20:
            groups.append([20])
            groups.append([1, 2, 4, 8])
            groups.append([3, 5, 9, 0])
            groups.append([6, 10, 12, 16])
            groups.append([7, 11, 13, 17])
            groups.append([21, 22, 23, 24, 14, 18])
            groups.append([15, 19])

        # Center of Mass: 0 (Base of Spine - Index cũ là 1) -> TÂM CỦA BẠN
        elif CoM == 0:
            groups.append([0])
            groups.append([1, 12, 16])
            groups.append([13, 17, 20])
            groups.append([2, 4, 8, 14, 18])
            groups.append([3, 5, 9, 15, 19])
            groups.append([6, 10])
            groups.append([7, 11, 21, 22, 23, 24])

        else:
            raise ValueError(f"Tham số CoM={CoM} không hợp lệ cho dữ liệu {dataset}")

    return groups

def get_edgeset(dataset='NTU', CoM=20):
    # Lấy các mảng nhóm đã chuẩn hóa sẵn ở index 0-24
    groups = get_groups(dataset=dataset, CoM=CoM)

    identity = []
    forward_hierarchy = []
    reverse_hierarchy = []

    for i in range(len(groups) - 1):
        self_link = groups[i] + groups[i + 1]
        self_link = [(node, node) for node in self_link] # Sửa biến i thành node để không trùng lặp
        identity.append(self_link)

        forward_g = []
        for j in groups[i]:
            for k in groups[i + 1]:
                forward_g.append((j, k))
        forward_hierarchy.append(forward_g)

        reverse_g = []
        for j in groups[-1 - i]:
            for k in groups[-2 - i]:
                reverse_g.append((j, k))
        reverse_hierarchy.append(reverse_g)

    edges = []
    for i in range(len(groups) - 1):
        edges.append([identity[i], forward_hierarchy[i], reverse_hierarchy[-1 - i]])

    return edges