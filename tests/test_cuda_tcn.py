"""验证系统的既有约定，使用测试样本或只读产物执行断言。
输入接口、特征或模型结果，输出可重复的自动化验证结论。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    import torch
    from train_station_tcn import TemporalCNN
except ImportError:
    torch = None


@unittest.skipUnless(
    torch is not None and torch.cuda.is_available(), "CUDA PyTorch environment is required"
)
class CudaTCNChecks(unittest.TestCase):
    def test_causal_hidden_states_and_real_cuda_gradient(self):
        """验证causal hidden states and real cuda gradient 对应的约定。"""
        torch.manual_seed(42)
        model = TemporalCNN(29, channels=16).cuda().eval()
        x = torch.randn(2, 29, 72, device="cuda")
        future = x.clone()
        future[:, :, 60:] += 100
        with torch.no_grad():
            old = model.blocks(x)
            new = model.blocks(future)
        self.assertTrue(old.is_cuda)
        self.assertTrue(torch.allclose(old[:, :, :60], new[:, :, :60], atol=1e-5, rtol=1e-5))
        prediction = model(x)
        self.assertEqual(tuple(prediction.shape), (2, 6))
        (prediction - 1).square().sum().backward()
        self.assertTrue(model.head.weight.grad.is_cuda)
        self.assertGreater(model.head.weight.grad.abs().sum().item(), 0)


if __name__ == "__main__":
    unittest.main()
