class Solution:
    def twoSum(self, nums: list[int], target: int) -> list[int]:
        map={}
        for idx in range(len(nums)):
            num = nums[idx]
            sub = target - num
            if map.get(sub):
                return [idx, map.get(sub)]
            map.update({num: idx})
