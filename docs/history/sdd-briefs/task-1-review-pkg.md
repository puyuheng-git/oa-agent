# Task 1 review package
## Files
- framework\com-lib\src\constant\user\LoginConst.php (exists)
- service\service-app\src\service\oa\user\Export.php (exists)
- service\service-app\src\service\oa\user\logic\AgentTokenImpl.php (exists)
- service\service-app\src\service\oa\user\Error.php (exists)

## FILE: framework\com-lib\src\constant\user\LoginConst.php
```php
<?php
/**
 * 登录常量
 * @filesource LoginConst.php
 * @author: wenxianghao
 * @date: 2020-10-27 16:57
 * @copyright Copyright(c)2020-2021,wenxianghao.cn. All Rights Reserved
 */

namespace lib\constant\user;

class LoginConst
{
    /**
     * 登录token过期时间
     */
    const LOGIN_EXPIRE_CUSTOMER = 86400 * 7;#客户
    const LOGIN_EXPIRE_COURSE = 86400 * 30;#报课
    const LOGIN_EXPIRE_EDU = 86400 * 7;#继续教育
    const LOGIN_EXPIRE_EMPLOY = 86400 * 7;#招聘
    const LOGIN_EXPIRE_BACKEND = 3600;#后台
    const LOGIN_DUSTESS_TAB = 1800;#尘锋tab页
    const LOGIN_WEWORK_CRM = 86400 * 7;#企业微信crm系统
    const LOGIN_EXPIRE_OFFICE = 1800; // 与 Agent ticket 对齐量级，可按需调

    /**
     * 登录token 业务编码
     */
    const TOKEN_BIZ_CODE_CUSTOMER = 'customer';#客户
    const TOKEN_BIZ_CODE_COURSE = 'course';#报课
    const TOKEN_BIZ_CODE_EDU = 'edu';#继续教育
    const TOKEN_BIZ_CODE_EMPLOY = 'employ';#招聘
    const TOKEN_BIZ_CODE_BACKEND = 'backend';#招聘
    const TOKEN_BIZ_CODE_DUSTESS = 'dustess';#尘锋tab页
    const TOKEN_BIZ_CODE_CRM = 'wework_crm';#企业微信crm系统
    const TOKEN_BIZ_CODE_OFFICE = 'office';
    /**
     * 默认token过期时间
     */
    const TOKEN_EXPIRE_DEFAULT = 86400 * 7;#默认
    /**
     * token过期时间配置
     */
    const TOKEN_EXPIRE = [
        self::TOKEN_BIZ_CODE_BACKEND => self::LOGIN_EXPIRE_BACKEND,
        self::TOKEN_BIZ_CODE_DUSTESS => self::LOGIN_DUSTESS_TAB,
        self::TOKEN_BIZ_CODE_CRM     => self::LOGIN_WEWORK_CRM,
        self::TOKEN_BIZ_CODE_OFFICE  => self::LOGIN_EXPIRE_OFFICE,
    ];

    const LOGIN_EXPIRE_ANSWER = 86400 * 7;#管会刷题
}
```

## FILE: service\service-app\src\service\oa\user\Export.php
```php
<?php
/**
 * 鐢ㄦ埛鏈嶅姟
 * @filesource Export.php
 * @author: wenxianghao
 * @date: 2020-08-25 13:42
 * @copyright Copyright(c)2020-2021,wenxianghao.cn. All Rights Reserved
 */

namespace app\service\oa\user;

use app\service\oa\user\logic\UserImpl;
use app\service\oa\user\logic\AgentTokenImpl;
use app\service\oa\user\logic\WechatUserImpl;
use app\service\oa\user\logic\WeworkUserImpl;
use lib\constant\common\CommonConst;
use lib\constant\user\LoginConst;
use lib\exception\Exception;
use lib\util\Passport;
use think\Collection;
use think\db\exception\DataNotFoundException;
use think\db\exception\DbException;
use think\db\exception\ModelNotFoundException;

class Export
{
    /**
     * 鑾峰彇鐢ㄦ埛鍒楄〃
     * @author: wenxianghao
     * @date: 2020-08-25 13:56
     * @param array $condition 鏌ヨ鏉′欢
     * @example [
     *  "USER_IDS" => [1,2,3]   //鐢ㄦ埛id鏁扮粍
     * ]
     * @param array $fields 鏌ヨ鐨勫瓧娈?
     * @return array
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function getList($condition, $fields = ['*'])
    {
        return UserImpl::getList($condition, $fields);
    }

    /**
     * 寰俊鎺堟潈
     * @author: wenxianghao
     * @date: 2020-08-26 16:40
     * @param string $uid 鐢ㄦ埛id
     * @param string $appId 寰俊搴旂敤id
     * @param array $data 寰俊鐢ㄦ埛淇℃伅
     * @return bool
     * @throws Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function bindWechatUser($uid, $appId, $data)
    {
        return WechatUserImpl::bind($uid, $appId, $data);
    }

    /**
     * 閫氳繃oa鍙疯幏鍙栫敤鎴疯鎯?
     * @author: wenxianghao
     * @date: 2020-08-31 20:15
     * @param string $userId oa鍙?
     * @param array $fields 鏌ヨ鐨勫瓧娈?
     * @return array
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function getUserInfoByUserId($userId, $fields = ['*'])
    {
        return UserImpl::getUserInfoByUserId($userId, $fields);
    }

    /**
     * 鍚屾oa鐢ㄦ埛鏁版嵁
     * @author: wenxianghao
     * @date: 2020-09-27 16:56
     * @return bool
     * @throws Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function syncOaUserData()
    {
        return UserImpl::syncOaUserData();
    }

    /**
     * 鑾峰彇娓稿濮撳悕
     * @author: wenxianghao
     * @date: 2021/3/11 8:15
     * @param int $uid 鐢ㄦ埛id
     * @return string
     */
    public function getVisitorName($uid)
    {
        return UserImpl::getVisitorName($uid);
    }

    /**
     * 閫氳繃鍒楄〃鏁版嵁鑾峰彇娓稿濮撳悕
     * @author: wenxianghao
     * @date: 2021/3/11 10:15
     * @param array $list 浜岀淮鍒楄〃鏁版嵁
     * @return array
     * @example [
     *  1 => "娓稿123",
     * ]
     */
    public function getVisitorNamesByList($list)
    {
        return UserImpl::getVisitorNamesByList($list);
    }

    /**
     * 濉厖鍒楄〃鏁版嵁鐢ㄦ埛淇℃伅
     * @author: wenxianghao
     * @date: 2021/4/7 14:57
     * @param array $originList 鍘熷鍒楄〃鏁版嵁
     * @param array $fillFields 闇€瑕佸～鍏呯殑瀛楁
     * @param string $foreignKey 澶栭敭鍚嶇О
     * @param string $localKey 鏈〃閿悕
     * @param array $opt 鍏朵粬鍙傛暟
     * @return array
     */
    public function fillUserList($originList, $fillFields, $foreignKey = 'uid', $localKey = 'uid', $opt = [])
    {
        return UserImpl::fillUserList($originList, $fillFields, $foreignKey, $localKey, $opt);
    }

    /**
     * 鏍规嵁uid鑾峰彇鐢ㄦ埛璇︽儏
     * User: zhangsikai
     * DateTime: 2021/7/28 18:13
     * Email: <xkmking1124@163.com>
     * @param $uid int 鐢ㄦ埛id
     * @param array $fields 鏌ヨ瀛楁
     * @return array
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function getUserInfo($uid, $fields = ['*'])
    {
        return UserImpl::getUserInfo($uid, $fields);
    }

    /**
     * 鎼滅储鐢ㄦ埛
     * @author: wenxianghao
     * @date: 2021/11/8 15:02
     * @param string $userName 鐢ㄦ埛濮撳悕
     * @param int $num 杩斿洖鏁版嵁鏉℃暟
     * @return array
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function search($userName, $num = CommonConst::PAGE_SIZE)
    {
        return UserImpl::search($userName, $num);
    }

    /**
     * 鏍规嵁鐢ㄦ埛鍚嶈幏鍙栫敤鎴蜂俊鎭?
     * @param string $userName 濮撳悕
     * @param string[] $fields 鏌ヨ瀛楁
     * @return array|\think\Model
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     * @author luxuelong
     * @date 2022/1/19 16:30
     */
    public function getUserInfoByUserName($userName, $fields = ['*'])
    {
        return UserImpl::getUserInfoByUserName($userName, $fields);
    }

    /**
     * 鏍规嵁鐢ㄦ埛鑾峰彇浼佷笟寰俊涓昏处鍙?
     * User: zhangsikai
     * DateTime: 2022/8/12 16:42
     * Email: <xkmking1124@163.com>
     * @param int $uid 鐢ㄦ埛id
     * @return false|mixed
     * @throws \lib\exception\Exception
     */
    public function getMainAccount(int $uid)
    {
        return UserImpl::getMainAccount($uid);
    }

    /**
     * 鑾峰彇鍦ㄨ亴浜哄憳鐨剋eworkuid
     * User: zhangsikai
     * DateTime: 2022/8/30 11:15
     * Email: <xkmking1124@163.com>
     * @return array
     * @throws Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function getWorkTrueUserList()
    {
        return WeworkUserImpl::getWorkTrueUserList();
    }

    /**
     * 鏍规嵁浼佷笟寰俊userid鑾峰彇鐢ㄦ埛OA
     * User: zhangsikai
     * DateTime: 2023/3/1 16:51
     * Email: <xkmking1124@163.com>
     * @param string $weworkUserId 浼佷笟寰俊userid
     * @return array
     * @throws Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function getUserIdsByWeworkId($weworkUserId)
    {
        return WeworkUserImpl::getUserIdsByWeworkId($weworkUserId);
    }

    /**
     * 鑾峰彇鎵归噺娓稿濮撳悕
     * @author: wenxianghao
     * @date: 2021/3/11 8:28
     * @param array $uids 鐢ㄦ埛id鏁扮粍
     * @return array
     * @example [
     *  1 => "娓稿123",
     * ]
     */
    public function getVisitorNames($uids)
    {
        return UserImpl::getVisitorNames($uids);
    }

    /**
     * 鏍规嵁浼佷笟寰俊uids鑾峰彇OA涓昏处鍙蜂俊鎭?
     * User: zhangsikai
     * DateTime: 2023/5/11 14:34
     * Email: <xkmking1124@163.com>
     * @param array $weworkIds 浼佷笟寰俊uid
     * @return array
     */
    public function getMainUserIdByWeworkIds($weworkIds)
    {
        return WeworkUserImpl::getMainUserIdByWeworkIds($weworkIds);
    }

    /**
     * 鏍规嵁鍙傛暟鑾峰彇浼佷笟鐢ㄦ埛uid
     * @author: puyueheng
     * @date: 2023/7/5 16:36
     * @param $params array 鏌ヨ鍙傛暟
     * @param $fields array 瀛楁
     * @return array
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public function getUserList(array $params, array $fields = []): array
    {
        return WeworkUserImpl::getUserList($params, $fields);
    }

    /**
     * 妫€娴嬬櫥褰?
     * @author: puyueheng
     * @date: 2023/6/1 15:51
     * @param string $token 鐧诲綍token
     * @param bool $refreshExpire 鏄惁鍒锋柊鐧诲綍token杩囨湡鏃堕棿
     * @param array $fields 鏌ヨ鐨勫瓧娈?
     * @return bool|array
     * @throws \lib\exception\Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */

    public static function checkLogin(string $token, bool $refreshExpire = true, array $fields = ['*'])
    {
        //妫€娴嬬櫥褰曪紝鑾峰彇token瑙ｆ瀽鐨勭敤鎴疯鎯?
        $userInfo = Passport::checkLogin(LoginConst::TOKEN_BIZ_CODE_OFFICE, $token, $refreshExpire);
        if (empty($userInfo))
        {
            return false;
        }
        $uid = $userInfo['id'];
        // 鎸?UID 鏌ュ簱锛岃繑鍥?DB 鐢ㄦ埛琛屼緵 AuthUser 璇诲彇 USER_ID / UID
        $user = UserImpl::getUserInfo($uid, $fields);
        if (empty($user))
        {
            return false;
        }
        return $user;
    }

    /**
     * 鑾峰彇鍒楀悕绉扮储寮曞€紀a
     * @author: zhaojianhao
     * @date: 2023/12/26 10:28
     * @param string $keyWord 鍏抽敭瀛?
     * @return array
     */
    public static function getColumnNameIndexkeyOa($keyWord = '')
    {
        return UserImpl::getColumnNameIndexkeyOa($keyWord);
    }

    /**
     * 鑾峰彇鍑借瘉鎿嶄綔浜洪儴闂ㄤ俊鎭?
     * @author: zhaojianhao
     * @date: 2024/2/5 10:15
     * @param array $oaArr 鎿嶄綔浜簅a鏁扮粍
     * @return array
     * @throws Exception
     */
    public static function getConfirmationOperatorDeptInfo($oaArr)
    {
        return UserImpl::getConfirmationOperatorDeptInfo($oaArr);
    }

    /**
     * 鑾峰彇鍦ㄨ亴鍛樺伐淇℃伅鏁扮粍
     * @author: zhaojianhao
     * @date: 2024/4/24 14:51
     * @param string $keyWord 鍚嶇О鎼滅储鍏抽敭瀛?
     * @return array
     */
    public static function getOnThejobStaffInfoArr($keyWord = '')
    {
        return UserImpl::getOnThejobStaffInfoArr($keyWord);
    }

    /**
     * 鑾峰彇鐢ㄦ埛淇℃伅鍒楄〃
     * @author: zhaojianhao
     * @date: 2024/4/24 15:45
     * @param array $userOaArr 鐢ㄦ埛oa鏁扮粍
     * @return array
     * @throws Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public static function getUserListByUserOaArr($userOaArr)
    {
        return UserImpl::getUserListByUserOaArr($userOaArr, 'USER_ID, USER_NAME');
    }

    /**
     * 鑾峰彇杈呭姪璐﹀彿oa鐢ㄦ埛淇℃伅鍒楄〃
     * @author: zhaojianhao
     * @date: 2024/4/29 10:57
     * @param array $userOaArr 鐢ㄦ埛oa鏁扮粍
     * @param array $search 鎼滅储鏉′欢
     * @return array
     * @throws Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public static function getAuxiliaryUserListByUserOaArr($userOaArr, $search = [])
    {
        return UserImpl::getUserListByUserOaArr($userOaArr, 'USER_ID as oa, USER_NAME as name, DEPT_ID as dept_id', $search);
    }

    /**
     * 鑾峰彇鎵€鏈夌敤鎴峰垪琛?
     * @author: chuzefang
     * @date: 2024/7/25 17:06
     * @param $fields array|string 鏌ヨ瀛楁
     * @return array
     * @throws DataNotFoundException
     * @throws DbException
     * @throws ModelNotFoundException
     */
    public function getAllUserList($fields = array())
    {
        return UserImpl::getAllUserList($fields);
    }

    /**
     * 鍛樺伐濮撳悕涓嬫媺鍒嗛〉
     * @author: chengfei
     * @date: 2026/7/2 18:01
     * @param array $params 鍙€? name_like
     * @param int $page 椤电爜
     * @param int $pageSize 姣忛〉鏉℃暟
     * @return array
     */
    public function getUserNameSelectPage($params = [], $page = 1, $pageSize = 20)
    {
        return UserImpl::getUserNameSelectPage($params, $page, $pageSize);
    }

    /**
     * 閫氳繃鐢ㄦ埛id鑾峰彇鐢ㄦ埛鍒楄〃
     * @author: chuzefang
     * @date: 2024/8/8 14:46
     * @param $userIds int|array 鐢ㄦ埛id
     * @param $fields array|string 鏌ヨ瀛楁
     * @return array
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException|\lib\exception\Exception
     */
    public function getUserListByUserIds($userIds, $fields = array('*'))
    {
        return UserImpl::getUserListByUserIds($userIds, $fields);
    }

    /**
     * 鑾峰彇閮ㄩ棬id渚濇嵁鐢ㄦ埛oa
     * @author: zhaojianhao
     * @date: 2024/9/10 15:36
     * @param string $oa 鐢ㄦ埛oa
     * @return string
     * @throws Exception
     */
    public function getDeptIdByOa($oa)
    {
        return UserImpl::getDeptIdByOa($oa);
    }

    /**
     * 鑾峰彇鐢ㄦ埛鍚嶅拰OA鍙锋槧灏勬暟缁?
     * @author: zhoubin
     * @date: 2024/12/18 11:01
     * @param $oas array OA鍙锋暟缁?
     * @return array
     */
    public function getOaNameMap($oas = [])
    {
        return UserImpl::getOaNameMap($oas);
    }

    /**
     * 鍖哄煙璋冩暣淇敼鍖哄煙宸ヤ綔璐﹀彿鍚嶇О<鍖虹粡鐞嗚处鍙?+鍖哄姪璐﹀彿>
     * @author: zhaojianhao
     * @date: 2024/12/11 10:38
     * @param array $params 璇锋眰鍙傛暟
     * @param array $operationLogInfo 鎿嶄綔璁板綍淇℃伅
     * @return bool
     * @throws Exception
     */
    public function updateWorkAccountByAreaAdjust($params, $operationLogInfo)
    {
        return UserImpl::updateWorkAccountByAreaAdjust($params, $operationLogInfo);
    }

    /**
     * 鑾峰彇鐢ㄦ埛鍚嶇О
     * @author: zhaojianhao
     * @date: 2025/1/10 11:31
     * @param string $userId 鐢ㄦ埛oa
     * @return mixed
     * @throws Exception
     */
    public function getUserNameByUserId($userId)
    {
        return UserImpl::getUserNameByUserId($userId);
    }

    /**
     * 鑾峰彇浼佷笟寰俊uid
     * User: lumingjie
     * DateTime: 2025/1/15 13:54
     * @param array $userIds 鐢ㄦ埛OA
     * @param bool $isMainAccount 鏄惁鏄富璐﹀彿
     * @return array
     * @throws DataNotFoundException
     * @throws DbException
     * @throws Exception
     * @throws ModelNotFoundException
     */
    public function getWeworkUserIdByUserIds($userIds, $isMainAccount = true)
    {
        return WeworkUserImpl::getWeworkUserIdByUserIds($userIds, $isMainAccount);
    }

    /**
     * 閫氳繃鐢ㄦ埛鍚嶇О鑾峰彇鐢ㄦ埛鍒楄〃
     * @author: chuzefang
     * @date: 2025/6/11 19:38
     * @param array $userNames 鐢ㄦ埛鍚嶇О
     * @param string[] $fields 鏌ヨ瀛楁
     * @return array
     * @throws \lib\exception\Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\ModelNotFoundException
     * @throws \think\exception\DbException
     */
    public function getUserListByUserNames($userNames, $fields = ['*'])
    {
        return UserImpl::getUserListByUserNames($userNames, $fields);
    }

    /**
     * 鑾峰彇鐢ㄦ埛鍚嶇О瀵瑰簲鐢ㄦ埛OA鏄犲皠鏁扮粍
     * @author: zhaojianhao
     * @date: 2025/6/19 20:24
     * @return array
     */
    public function getUserNameIndexKeyOa()
    {
        return UserImpl::getUserNameIndexKeyOa();
    }

    /**
     * 鏍规嵁杈撳叆鐨勬枃瀛楀尮閰嶇敤鎴峰悕
     * @author: xufeng
     * @date: 2025/7/25 10:42
     * @param $name string 杈撳叆鐨勬枃瀛?
     * @return array
     */
    public function getMatchedUserName($name)
    {
        return UserImpl::getMatchedUserName($name);
    }

    /**
     * 鑾峰彇鐢ㄦ埛閮ㄩ棬淇℃伅
     * @author: zhaojianhao
     * @date: 2025/9/21 16:52
     * @param array $userOaArr 鐢ㄦ埛OA鏁扮粍
     * @return array
     */
    public function getUserDeptInfoList($userOaArr = [])
    {
        return UserImpl::getUserDeptInfoList($userOaArr);
    }

    /**
     * 鎵归噺鑾峰彇鐢ㄦ埛淇℃伅
     * @author: xufeng
     * @date: 2025/10/14 14:30
     * @param $userIds  array 鐢ㄦ埛oa鏁扮粍
     * @param $fields array 鏌ヨ瀛楁
     * @return array
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\ModelNotFoundException
     * @throws \think\exception\DbException
     */
    public function batchGetUserInfoByUserIds($userIds, $fields = ['*'])
    {
        return UserImpl::batchGetUserInfoByUserIds($userIds, $fields);
    }

    /**
     * 鏍规嵁 weworkUserId 鏁扮粍 鑾峰彇瀵瑰簲鐨勬槧灏勫叧绯?
     * User: zhangsikai
     * DateTime: 2026/1/7 17:49
     * Email: <xkmking1124@163.com>
     * @param $userIds
     * @return array
     */
    public function getWeworkUserIdMap2OaByWeworkUserIdArr($userIds)
    {
        return WeworkUserImpl::getWeworkUserIdMap2OaByWeworkUserIdArr($userIds);
    }

    /**
     * 鑾峰彇鐢ㄦ埛淇℃伅
     * @author: chengfei
     * @date: 2026/2/2 涓嬪崍4:39
     * @param $params array 鏌ヨ鏉′欢鏁扮粍
     * @param $fields array 鏌ヨ瀛楁鏁扮粍
     * @return array
     * @throws DataNotFoundException
     * @throws ModelNotFoundException
     * @throws \think\Exception
     * @throws \think\exception\DbException
     */
    public function getWeWorkUserInfo($params, $fields = [])
    {
        return WeworkUserImpl::getWeWorkUserInfo($params, $fields);
    }

    /**
     * 鎸夌敤鎴峰鍚嶆壒閲忚幏鍙? OA 鏄犲皠锛堣€冨嫟瀹℃壒浜虹瓑鍦烘櫙锛氬鎵逛汉濮撳悕 鈫? user_id/OA锛?
     * @author liuhaonan
     * @date 2026/9/1 10:20
     * @param array $userNames 鐢ㄦ埛濮撳悕鍒楄〃锛坱d_oa.user.USER_NAME锛?
     * @return array key=鐢ㄦ埛濮撳悕锛寁alue=OA锛坲ser_id锛夛紱鍚屽悕澶氭潯鏃跺悗鑰呰鐩栧墠鑰?
     * @throws \think\db\exception\DbException
     */
    public function getUserOaMapByUserNames(array $userNames): array
    {
        return UserImpl::getUserOaMapByUserNames($userNames);
    }

    /**
     * Agent 缃戝叧绛惧彂 office Authorization
     * @author: puyueheng
     * @date: 2026/9/23
     * @param string $oa OA 璐﹀彿(USER_ID)
     * @param string $gatewaySecret 缃戝叧鍏变韩瀵嗛挜
     * @param string $operateUser 鎿嶄綔鏂规爣璇嗭紝榛樿 agent-gateway
     * @return array authorization/uid/oa/expire
     * @throws Exception
     * @throws DataNotFoundException
     * @throws DbException
     * @throws ModelNotFoundException
     */
    public function agentMintOfficeToken(string $oa, string $gatewaySecret, string $operateUser = 'agent-gateway'): array
    {
        return AgentTokenImpl::mint($oa, $gatewaySecret, $operateUser);
    }
}

```

## FILE: service\service-app\src\service\oa\user\logic\AgentTokenImpl.php
```php
<?php
/**
 * Agent 网关签发 office token
 * @filesource AgentTokenImpl.php
 * @author: puyueheng
 * @date: 2026/9/23
 * @copyright Copyright(c)2020-2021,dscpa.cn. All Rights Reserved
 */

namespace app\service\oa\user\logic;

use app\service\oa\user\Error;
use lib\constant\user\LoginConst;
use lib\exception\Exception;
use lib\util\DuplicateSubmit;
use lib\util\Passport;
use think\facade\Log;

class AgentTokenImpl
{
    /**
     * 防重复提交业务键
     */
    const DUP_KEY = 'oa.user.agentMintOfficeToken';

    /**
     * 校验网关密钥并为指定 OA 签发 office Authorization
     * @author: puyueheng
     * @date: 2026/9/23
     * @param string $oa OA 账号（USER_ID）
     * @param string $gatewaySecret 网关共享密钥
     * @param string $operateUser 操作方标识，默认 agent-gateway
     * @return array authorization/uid/oa/expire
     * @throws Exception
     * @throws \think\db\exception\DataNotFoundException
     * @throws \think\db\exception\DbException
     * @throws \think\db\exception\ModelNotFoundException
     */
    public static function mint(string $oa, string $gatewaySecret, string $operateUser = 'agent-gateway'): array
    {
        // 校验网关共享密钥（空密钥一律拒绝）
        $expectedSecret = (string)env('AGENT_GATEWAY_SECRET', '');
        if ($expectedSecret === '' || !hash_equals($expectedSecret, (string)$gatewaySecret))
        {
            throw Exception::user(Error::AGENT_GATEWAY_SECRET_INVALID);
        }
        // 写路径防重复提交
        DuplicateSubmit::assert($operateUser, self::DUP_KEY, 3);
        // 规范化 OA 并查库
        $oa = trim($oa);
        if ($oa === '')
        {
            DuplicateSubmit::clear($operateUser, self::DUP_KEY);
            throw Exception::user(Error::AGENT_OA_EMPTY);
        }
        $user = UserImpl::getUserInfoByUserId($oa, ['UID', 'USER_ID', 'NOT_LOGIN']);
        if (empty($user) || empty($user['UID']))
        {
            DuplicateSubmit::clear($operateUser, self::DUP_KEY);
            throw Exception::user(Error::AGENT_USER_NOT_FOUND);
        }
        // 禁止登录账号不可签发
        if (!empty($user['NOT_LOGIN']))
        {
            DuplicateSubmit::clear($operateUser, self::DUP_KEY);
            throw Exception::user(Error::AGENT_USER_DENY_LOGIN);
        }
        $uid = (int)$user['UID'];
        // Passport 载荷至少含 id=UID，便于 checkLogin 按 UID 还原用户
        $payload = [
            'id' => $uid,
            'oa' => $user['USER_ID'],
        ];
        $token = Passport::genAuthorization(LoginConst::TOKEN_BIZ_CODE_OFFICE, $payload);
        if (empty($token))
        {
            DuplicateSubmit::clear($operateUser, self::DUP_KEY);
            throw Exception::user(Error::AGENT_MINT_TOKEN_FAIL);
        }
        $expire = time() + LoginConst::LOGIN_EXPIRE_OFFICE;
        // 审计：谁为哪个 oa 签发了 office token
        Log::info('agentMintOfficeToken', [
            'oa'           => $user['USER_ID'],
            'uid'          => $uid,
            'operate_user' => $operateUser,
            'time'         => date('Y-m-d H:i:s'),
            'expire'       => $expire,
        ]);
        return [
            'authorization' => $token,
            'uid'           => $uid,
            'oa'            => $user['USER_ID'],
            'expire'        => $expire,
        ];
    }
}

```

## FILE: service\service-app\src\service\oa\user\Error.php
```php
<?php
/**
 * OA 用户模块错误码
 * @filesource Error.php
 * @author: puyueheng
 * @date: 2026/9/23
 * @copyright Copyright(c)2020-2021,dscpa.cn. All Rights Reserved
 */

namespace app\service\oa\user;

class Error
{
    /**
     * Agent 网关密钥无效
     */
    const AGENT_GATEWAY_SECRET_INVALID = 1000280101;
    /**
     * Agent 签发 office token 时 OA 为空
     */
    const AGENT_OA_EMPTY = 1000280102;
    /**
     * Agent 签发目标用户不存在
     */
    const AGENT_USER_NOT_FOUND = 1000280103;
    /**
     * Agent 签发目标账号禁止登录
     */
    const AGENT_USER_DENY_LOGIN = 1000280104;
    /**
     * office token 签发失败
     */
    const AGENT_MINT_TOKEN_FAIL = 1000280105;

    const CODE_MAP = [
        self::AGENT_GATEWAY_SECRET_INVALID => '网关密钥无效',
        self::AGENT_OA_EMPTY               => 'OA账号不能为空',
        self::AGENT_USER_NOT_FOUND         => '用户不存在',
        self::AGENT_USER_DENY_LOGIN        => '账号禁止登录',
        self::AGENT_MINT_TOKEN_FAIL        => '签发登录令牌失败',
    ];
}

```
