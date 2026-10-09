
#ifndef HCANBUS_H
#define HCANBUS_H

#if defined(_WIN32) || defined(__CYGWIN__) || defined(_WIN32_WCE)
#define LIBUSB_CALL WINAPI
#else
#define LIBUSB_CALL
#endif

#define        DEVTYP_CAN                    0x00     //CAN2.0
#define        DEVTYP_CANFD                  0x01     //CANFD
#define        DEVTYP_LIN                    0x02     //LIN

#define        CANCFG_INTREN                 0x01     //使能内部电阻(仅对用电子开关控制电阻的设备有效)
#define        CANCFG_OFFWKUP                0x02     //离线唤醒
#define        CANCFG_AUTORTX                0x04     //自动重传

#define        CANMOD_NORM                   0x00     //正常模式
#define        CANMOD_LOOPBACK               0x01     //环回模式
#define        CANMOD_SILENT                 0x02     //静默模式
#define        CANMOD_SILENTLOOPBACK         0x03     //静默环回模式

#define        CANTYP_CAN                    0x00     //CAN2.0
#define        CANTYP_ISOCANFD               0x01     //ISO CANFD
#define        CANTYP_NONISOCANFD            0x02     //Non-ISOCANFD

#define        CANEXTFLG_STD                 0x00     //标准帧
#define        CANEXTFLG_EXT                 0x01     //扩展帧
#define        CANREMFLG_DATA                0x00     //数据帧
#define        CANREMFLG_REM                 0x01     //远程帧

#define        CANFMTYP_DIRRX                0x00     //接收帧
#define        CANFMTYP_DIRTX                0x01     //发送帧
#define        CANFMTYP_XFRSUCC              0x00     //传输成功
#define        CANFMTYP_XFRFAIL              0x02     //传输失败
#define        CANFMTYP_CAN                  0x00     //CAN数据帧
#define        CANFMTYP_CANFD                0x04     //CANFD数据帧
#define        CANFMTYP_FDBRS                0x08     //FDBRS数据帧
#define        CANFMTYP_TMSTA                0x10     //定时发送开始标识
#define        CANFMTYP_TMEND                0x20     //定时发送结束标识
#define        CANFMTYP_ECHO                 0x40     //发送数据回传

#define        CANBUSSTA_ERRWRN              0x01     //错误警告
#define        CANBUSSTA_ERRPAS              0x02     //错误被动
#define        CANBUSSTA_BUSOFF              0x04     //总线离线
#define        CANBUSSTA_NORM                0x08     //总线正常
#define        CANBUSSTA_ARBERR              0x10     //仲裁错误
#define        CANBUSSTA_MBEMP               0x20     //发送邮箱空
#define        CANBUSSTA_RXOVF               0x40     //接收寄存器溢出
#define        CANBUSSTA_RXFUL               0x80     //接收寄存器满

#define        CANERRSTA_BIT                 0x01     //位填充错
#define        CANERRSTA_FORM                0x02     //格式错误
#define        CANERRSTA_ACK                 0x03     //确认错误
#define        CANBUSSTA_REC                 0x04     //隐形位错
#define        CANBUSSTA_DOM                 0x05     //显性位错
#define        CANBUSSTA_CRC                 0x06     //CRC错

#define        LINMOD_MSTSLV                 0x00     //主从模式
#define        LINMOD_MST                    0x01     //主机模式
#define        LINMOD_SLV                    0x02     //从机模式

#define        LINPOW_OFF                    0x00     //LIN电源关闭
#define        LINPOW_ON                     0x01     //LIN电源开启(仅对有内部电源的设备有效)
#define        LINFMTYP_DIRRX                0x00     //接收帧
#define        LINFMTYP_DIRTX                0x01     //发送帧

#define        LINCHKTYP_ERR                 0x00     //校验错误
#define        LINCHKTYP_CLA                 0x01     //常规校验
#define        LINCHKTYP_ENH                 0x02     //增强校验
#define        LINCHKTYP_HED                 0x03     //仅Header



typedef  struct  _Dev_Info {
	char            HW_Type[32]; //设备型号 字符串
	char            HW_Ser[32];  //设备序列号 字符串 
	char            HW_Ver[32];  //硬件版本 字符串
	char            FW_Ver[32];  //软件版本 字符串
	char            MF_Date[32]; //生产日期 字符串
} Dev_Info, *PDev_Info;

typedef struct  _Can_Config {
	unsigned int    Baudrate;
	unsigned short  Pres;        // Pres,Tseg1,Tseg2如果与Baudrate不匹配，动态库会自动按
	unsigned char   Tseg1;       // Baudrate重新计算Pres,Tseg1,Tseg2,SJW并且采样点设置为
	unsigned char   Tseg2;       // 75%左右。一般情况可以只设置波特率，Pres,Tseg1,Tseg2填0
	unsigned char   SJW;
	unsigned char   Config;      //配置信息：0x01接通内部电阻 0x02离线唤醒 0x04自动重传
	unsigned char   Model;       //工作模式：0 正常模式,1 环回模式,2 静默模式,3 静默环回模式
	unsigned char   Reserved;    //保留
}Can_Config, *P_Can_Config;

typedef struct  _CanFD_Config {
	unsigned int    NomBaud;     //常规波特率
	unsigned int    DatBaud;     //数据波特率
	unsigned short  NomPre;      // NomPre,NomTseg1,NomTseg2如果与NomBaud不匹配，动态库会自动按
	unsigned char   NomTseg1;    // NomBaud重新计算NomPre,NomTseg1,NomTseg2,NomSJW并且采样点设置为
	unsigned char   NomTseg2;    // 75%左右。这些值可借助波特率计算器计算后设置
	unsigned char   NomSJW;
	unsigned char   DatPre;      // DatPre,DatTseg1,DatTseg2如果与DatBaud不匹配，动态库会自动按
	unsigned char   DatTseg1;    // DatBaud重新计算DatPre,DatTseg1,DatTseg2,DatSJW并且采样点设置为
	unsigned char   DatTseg2;    // 75%左右。这些值可借助波特率计算器计算后设置
	unsigned char   DatSJW;
	unsigned char   Config;      //配置信息：0x01接通内部电阻 0x02离线唤醒 0x04自动重传
	unsigned char   Model;       //工作模式：0 正常模式,1 环回模式,2 静默模式,3 静默环回模式
	unsigned char   Cantype;     //CAN模式： 0 CAN,1 IOS CANFD,2 Non-ISO CANFD
}CanFD_Config, *P_CanFD_Config;

typedef  struct  _Can_Msg {
	unsigned int    ID;          //报文ID
	unsigned int    TimeStamp;   //微秒级时间戳
	unsigned char   FrameType;   //帧类型
	unsigned char   DataLen;     //有效字节数
	unsigned char   ExternFlag;  //扩展帧标识：0标准帧,1扩展帧
	unsigned char   RemoteFlag;  //远程帧标识：0数据帧,1远程帧
	unsigned char   BusSatus;    //总线状态
	unsigned char   ErrSatus;    //错误状态
	unsigned char   TECounter;   //发送错误计数
	unsigned char   RECounter;   //接收错误计数
	unsigned char   Data[8];     //报文数据
}Can_Msg, *P_Can_Msg;

typedef  struct  _CanFD_Msg {
	unsigned int    ID;          //报文ID
	unsigned int    TimeStamp;   //微秒级时间戳
	unsigned char   FrameType;   //帧类型
	unsigned char   DLC;         //DLC不等于数据长度。最大值15，对于数据长度64
	unsigned char   ExternFlag;  //扩展帧标识：0标准帧,1扩展帧
	unsigned char   RemoteFlag;  //远程帧标识：0数据帧,1远程帧
	unsigned char   BusSatus;    //总线状态
	unsigned char   ErrSatus;    //错误状态
	unsigned char   TECounter;   //发送错误计数
	unsigned char   RECounter;   //接收错误计数
	unsigned char   Data[64];    //报文数据
}CanFD_Msg, *P_CanFD_Msg;

typedef struct  _Lin_Config {
        unsigned int    Baudrate;
        unsigned char   Model;       //工作模式：0 主从混合模式,1 主机模式,2 从机模式
        unsigned char   DCPower;     //12v电源输出使能： 0 无输出,1 输出12V电源
        unsigned char   Reserved1;   //保留
        unsigned char   Reserved2;   //保留
}Lin_Config;

typedef struct  _Lin_Msg{
        unsigned int   TimeStamp;
        unsigned char  ID;
        unsigned char  DataLen;
        unsigned char  Checksum;
        unsigned char  Checktype;   //0 校验错误 1 标准校验 2 增强校验 3 Header
        unsigned char  FrameType;   //0 接收 1 发送
        unsigned char  Reserved1;
        unsigned char  Reserved2;
        unsigned char  Reserved3;
        unsigned char  Data[8];
}Lin_Msg, *P_Lin_Msg;

typedef struct  _Lin_SlaveMsg{
        unsigned char  ID;
        unsigned char  DataLen;
        unsigned char  Checktype;    //1 标准校验 2 增强校验
        unsigned char  Reserved;     //保留
        unsigned char  Data[8];
}Lin_SlaveMsg, *P_Lin_SlaveMsg;

typedef struct  _Can_Status {
	unsigned char   BusSatus;    //总线状态
	unsigned char   ErrSatus;    //错误状态
	unsigned char   TECounter;   //发送错误计数
	unsigned char   RECounter;   //接收错误计数
	unsigned int    TimeStamp;   //产生状态时的时间戳
}Can_Status, *P_Can_Status;

#ifdef __cplusplus
extern "C" {
#endif

int __stdcall   Reg_HotPlug_Func(void(*pfunc)(void));   //热拔插函数 
int __stdcall   CAN_ScanDevice(void);                   //扫描CAN,CANFD设备

int __stdcall   CAN_OpenDevice(unsigned int devNum);    //打开CAN,CANFD设备
int __stdcall   CAN_CloseDevice(unsigned int devNum);   //关闭CAN,CANFD设备

int __stdcall   CAN_GetDevType(unsigned int devNum);     //获取CAN,CANFD类型 0：常规CAN，1：CANFD,  2 : LIN
int __stdcall   CAN_GetDevPlck(unsigned int devNum);     //获取CAN,CANFD主频
int __stdcall   CAN_ReadDevInfo(unsigned int devNum, PDev_Info devinfo);  //读取CAN,CANFD设备信息

int __stdcall   CAN_GetTimeStamp(unsigned int devNum,unsigned int *timestamp); //获取CAN,CANFD时间戳
int __stdcall   CAN_SetTimeStamp(unsigned int devNum,unsigned int timestamp,char mode);//设置CAN,CANFD时间戳  mode 0：设置当前通道，1设置同硬件所有通道

int __stdcall   CAN_GetDevID(unsigned int devNum, unsigned int *id); //获取CAN,CANFD通道ID，相当于地址，使用多个设备时便于区分CAN通道
int __stdcall   CAN_SetDevID(unsigned int devNum, unsigned int id);  //配置CAN,CANFD通道ID

int __stdcall   CAN_SetFilter(unsigned int devNum,char namber, char type, unsigned int ftID, unsigned int ftMask, char enable); //设置CAN,CANFD硬件屏蔽
int __stdcall   CAN_Reset(unsigned int devNum);         //复位CAN,CANFD设备
int __stdcall   CAN_GetStatus(unsigned int devNum,P_Can_Status status);        //获取CAN,CANFD设备状态

int __stdcall   CAN_Init(unsigned int devNum,P_Can_Config pInitConfig);   //初始化CAN设备
int __stdcall   CAN_Transmit(unsigned int devNum, P_Can_Msg canmsg, unsigned int items, int timeou);  //发送CAN报文
int __stdcall   CAN_TransmitRt(unsigned int devNum, P_Can_Msg canmsg, unsigned int items, unsigned int *txitems, int timeou);   //定时发送CAN报文
int __stdcall   CAN_GetReceiveNum(unsigned int devNum); //获取接收缓冲区中接收到但尚未被读取的帧数量
int __stdcall   CAN_Receive(unsigned int devNum,P_Can_Msg canmsg, int items, int timeou);  //接收CAN报文

int __stdcall   CANFD_Init(unsigned int devNum, P_CanFD_Config pInitConfig);
int __stdcall   CANFD_Transmit(unsigned int devNum, P_CanFD_Msg canmsg, unsigned int items, int timeout);
int __stdcall   CANFD_TransmitRt(unsigned int devNum, P_CanFD_Msg canmsg, unsigned int items, unsigned int *txitems, int timeou);   //定时发送CAN报文
int __stdcall   CANFD_GetReceiveNum(unsigned int devNum);//获取接收缓冲区中接收到但尚未被读取的帧数量
int __stdcall   CANFD_Receive(unsigned int devNum, P_CanFD_Msg canmsg, unsigned int items, int timeout); //接收CANFD报文

int __stdcall   LIN_OpenDevice(unsigned int devNum,  Lin_Config linconfig);//打开并配置LIN通道
int __stdcall   LIN_CloseDevice(unsigned int devNum);//关闭LIN通道
int __stdcall   LIN_Transmit(unsigned int devNum, P_Lin_Msg canmsg, unsigned int items, int timeout);//主机发送LIN数据
int __stdcall   LIN_Receive(unsigned int devNum, P_Lin_Msg canmsg, unsigned int items, int timeout);//接收LIN数据
int __stdcall   LIN_SetSlaveMsgs(unsigned int devNum, P_Lin_SlaveMsg canmsg, unsigned int items);//设置从机响应数据


#ifdef __cplusplus
}
#endif 

#endif



